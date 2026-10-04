"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { flush, pending, subscribe } from "@/lib/offline";
import { Badge, Empty, Notice, Skeleton } from "@/components/ui";
import { STATE_SHORT, stateTone } from "@/components/field";

type Run = S["RunOut"];

const dayFmt = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
const timeFmt = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
const dayKey = (iso: string) => new Date(iso).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

function dayName(iso: string): string {
  const k = dayKey(iso);
  const today = dayKey(new Date().toISOString());
  const tomorrow = dayKey(new Date(Date.now() + 86_400_000).toISOString());
  const label = dayFmt.format(new Date(iso));
  if (k === today) return `Today, ${label}`;
  if (k === tomorrow) return `Tomorrow, ${label}`;
  return label;
}

/** Short guidance for the list; the full sentence is on the task page. */
function nextShort(r: Run, all: Run[]): string {
  if (r.state === "assigned") return "Accept the task";
  if (r.state === "accepted") {
    const open = r.depends_on.filter((d) => {
      const dep = all.find((x) => x.task_ref === d);
      return dep && !["verifier_review", "closed"].includes(dep.state);
    });
    return open.length ? `Waiting for ${open.join(", ")}` : "Check in on site";
  }
  if (r.state === "checked_in") return "Confirm backup and access";
  if (r.state === "prechecks_done") {
    const done = r.steps.filter((s) => s.done).length;
    return done < r.steps.length ? `Step ${done + 1} of ${r.steps.length}` : "Record the values";
  }
  if (r.state === "configured") return r.rework_count ? "Fix what was sent back" : "Add the evidence";
  if (r.state === "engine_check") return "Get the hand over code";
  if (r.state === "verifier_review") return "Waiting for a verifier";
  if (r.state === "blocked") return `Blocked: ${r.block_reason ?? ""}`;
  return STATE_SHORT[r.state] ?? r.state;
}

export default function MyTasks() {
  const { can } = useMe();
  const runs = useData<Run[]>(can("field:work") ? "/field/my" : null);
  const [waiting, setWaiting] = useState(0);
  useEffect(() => {
    const read = () => void pending().then((p) => setWaiting(p.length));
    read();
    return subscribe(read);
  }, []);

  if (!can("field:work")) return <Notice tone="warn">This page is for field engineers.</Notice>;

  const list = runs.data ?? [];
  const groups = new Map<string, Run[]>();
  for (const r of list) {
    const k = dayKey(r.planned_start);
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }

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

      {runs.error && <Notice tone="bad">{runs.error}</Notice>}
      {runs.loading && !runs.data && <Skeleton lines={6} />}
      {runs.data && list.length === 0 && (
        <Empty title="No tasks for you right now">
          When a project manager starts field work, your tasks appear here with their dates.
        </Empty>
      )}

      <ul className="tasklist">
        {[...groups.entries()].map(([k, rs]) => (
          <li key={k}>
            <h2 className="day">{dayName(rs[0].planned_start)}</h2>
            <ul className="tasklist">
              {rs.map((r) => (
                <li key={r.id}>
                  <Link className="task" href={`/field/${r.id}`}>
                    <span className="title">
                      <span className="mono muted">{r.task_ref}</span> {r.title}
                    </span>
                    <span className="when">{timeFmt.format(new Date(r.planned_start))}</span>
                    <span className="next">
                      <Badge tone={stateTone(r.state)}>{STATE_SHORT[r.state]}</Badge> {nextShort(r, list)}
                      {r.asset ? <span className="muted">, {r.asset}</span> : null}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
