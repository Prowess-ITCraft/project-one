"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { flush, pending, subscribe } from "@/lib/offline";
import { Badge, Empty, Notice, Skeleton } from "@/components/ui";
import { STATE_SHORT, shortTitle, stateTone } from "@/components/field";

type Run = S["MyRunOut"];

const dayFmt = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
const timeFmt = new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
const dayKey = (iso: string) => new Date(iso).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

function dayName(iso: string): string {
  const k = dayKey(iso);
  const today = dayKey(new Date().toISOString());
  const tomorrow = dayKey(new Date(Date.now() + 86_400_000).toISOString());
  const label = dayFmt.format(new Date(iso));
  if (k < today) return `Overdue, ${label}`;
  if (k === today) return `Today, ${label}`;
  if (k === tomorrow) return `Tomorrow, ${label}`;
  return label;
}

/** Prerequisite tasks in the same project that are not handed over yet. Task refs restart in
 * every project, so the project has to match as well as the ref. */
function openDeps(r: Run, all: Run[]): string[] {
  return r.depends_on.filter((d) => {
    const dep = all.find((x) => x.project_id === r.project_id && x.task_ref === d);
    return dep && !["verifier_review", "closed"].includes(dep.state);
  });
}

/** Short guidance for the list; the full sentence is on the task page. */
function nextShort(r: Run, all: Run[]): string {
  if (r.state === "assigned") return "Accept the task";
  if (r.state === "accepted") {
    const open = openDeps(r, all);
    return open.length ? `Waiting for ${open.join(", ")} to be handed over` : "Check in on site";
  }
  if (r.state === "checked_in") return "Confirm backup and access";
  if (r.state === "prechecks_done") {
    const done = r.steps.filter((s) => s.done).length;
    return done < r.steps.length ? `Step ${done + 1} of ${r.steps.length}` : "Record the values";
  }
  if (r.state === "configured") return r.rework_count ? "Fix what was sent back" : "Add the evidence";
  if (r.state === "evidence_uploaded") return "Run the check";
  if (r.state === "engine_check") return "Get the hand over code";
  if (r.state === "verifier_review") return "Waiting for a verifier";
  if (r.state === "blocked") return r.block_reason ? `Blocked: ${r.block_reason}` : "Blocked";
  return STATE_SHORT[r.state] ?? r.state;
}

/** Does the engineer have something to do on this task right now? */
function needsYou(r: Run, all: Run[]): boolean {
  if (r.state === "verifier_review" || r.state === "blocked") return false;
  if (r.state === "accepted" && openDeps(r, all).length) return false;
  return true;
}

function where(r: Run): string | null {
  if (!r.project) return null;
  return r.project.customer ? `${r.project.customer}, ${r.project.name}` : r.project.name;
}

function TaskRow({ r, all, showDay }: { r: Run; all: Run[]; showDay?: boolean }) {
  const title = shortTitle(r.title, r.asset);
  const at = new Date(r.planned_start);
  return (
    <li>
      <Link className="task" href={`/field/${r.id}`}>
        <span className="title">
          <span className="mono muted">{r.task_ref}</span> {title}
        </span>
        <span className="when">{showDay ? `${dayFmt.format(at)}, ${timeFmt.format(at)}` : timeFmt.format(at)}</span>
        {(r.asset || where(r)) && (
          <span className="where">
            {r.asset && <span className="asset">{r.asset}</span>}
            {where(r) && <span className="muted">{where(r)}</span>}
          </span>
        )}
        <span className="next">
          <Badge tone={stateTone(r.state)}>{STATE_SHORT[r.state]}</Badge> {nextShort(r, all)}
        </span>
      </Link>
    </li>
  );
}

export default function MyTasks() {
  const { can } = useMe();
  const runs = useData<Run[]>(can("field:work") ? "/field/my" : null);
  const [waiting, setWaiting] = useState(0);
  const [project, setProject] = useState("all");
  useEffect(() => {
    const read = () => void pending().then((p) => setWaiting(p.length));
    read();
    return subscribe(read);
  }, []);

  const all = useMemo(() => runs.data ?? [], [runs.data]);
  const projects = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of all) m.set(r.project_id, r.project ? `${r.project.name} (${r.project.code})` : "Project");
    return [...m.entries()];
  }, [all]);
  const shown = project === "all" ? all : all.filter((r) => r.project_id === project);
  const now = shown.filter((r) => needsYou(r, all));
  const later = shown.filter((r) => !needsYou(r, all));
  const days = new Map<string, Run[]>();
  for (const r of now) {
    const k = dayKey(r.planned_start);
    days.set(k, [...(days.get(k) ?? []), r]);
  }

  if (!can("field:work")) return <Notice tone="warn">This page is for field engineers.</Notice>;

  return (
    <div className="field-page">
      <div className="page-head">
        <div>
          <h1>My tasks</h1>
          <p>Open a task to see the next step. Work you do without signal is kept on this phone and sent later.</p>
        </div>
      </div>
      {runs.stale && <Notice tone="warn">No signal. This is what was loaded earlier; anything you do is saved on this phone and sent when signal returns.</Notice>}

      {waiting > 0 && (
        <div className="outbox-note row between">
          <span>
            {waiting} action{waiting === 1 ? "" : "s"} saved on this phone, not sent yet.
          </span>
          <button className="btn small" onClick={() => void flush().then(() => runs.reload())}>
            Send now
          </button>
        </div>
      )}

      {runs.error && !runs.data && <Notice tone="bad">{runs.error}</Notice>}
      {runs.loading && !runs.data && <Skeleton lines={6} />}
      {runs.data && all.length === 0 && (
        <Empty title="No tasks for you right now">When a project manager starts field work, your tasks appear here with their dates.</Empty>
      )}

      {projects.length > 1 && (
        <div className="field task-filter">
          <label htmlFor="proj">Project</label>
          <select id="proj" value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="all">All projects ({all.length} tasks)</option>
            {projects.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </div>
      )}

      {runs.data && all.length > 0 && (
        <>
          <h2 className="tasks-head">
            Needs you <span className="muted">({now.length})</span>
          </h2>
          {now.length === 0 ? (
            <p className="muted">Nothing to do right now. Tasks waiting on someone else are listed below.</p>
          ) : (
            <ul className="tasklist">
              {[...days.entries()].map(([k, rs]) => (
                <li key={k}>
                  <h3 className="day">{dayName(rs[0].planned_start)}</h3>
                  <ul className="tasklist">
                    {rs.map((r) => (
                      <TaskRow key={r.id} r={r} all={all} />
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}

          {later.length > 0 && (
            <details className="tasks-later">
              <summary>
                Waiting on someone else <span className="muted">({later.length})</span>
              </summary>
              <p className="muted small">Blocked, waiting for an earlier task, or handed over and waiting for a verifier.</p>
              <ul className="tasklist">
                {later.map((r) => (
                  <TaskRow key={r.id} r={r} all={all} showDay />
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
