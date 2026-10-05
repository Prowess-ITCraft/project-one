"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { dateTime, get, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton, useAction } from "@/components/ui";
import { STATE_SHORT, StateTrace, stateTone } from "@/components/field";

type Ev = S["EventOut"];

/** Live events: server-sent events while the tab is open, polling if the stream is refused. */
function useLiveEvents(projectId: string, enabled: boolean, onEvent: () => void) {
  const [events, setEvents] = useState<(Ev & { fresh?: boolean })[]>([]);
  const cursor = useRef(0);
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    let poll: ReturnType<typeof setInterval> | undefined;
    let es: EventSource | undefined;
    // Many events can arrive together; the lists are reloaded once for the lot.
    let pending: ReturnType<typeof setTimeout> | undefined;
    const take = (list: Ev[], fresh: boolean) => {
      const seen = cursor.current;
      const news = list.filter((e) => e.seq > seen);
      if (!news.length) return;
      cursor.current = Math.max(seen, ...news.map((e) => e.seq));
      setEvents((x) => [...news.map((e) => ({ ...e, fresh })).reverse(), ...x].slice(0, 60));
      if (fresh && !pending) {
        pending = setTimeout(() => {
          pending = undefined;
          cb.current();
        }, 1_000);
      }
    };
    // Start from the newest events, however long the project's history is.
    void get<Ev[]>(`/projects/${projectId}/field/events?latest=true&limit=40`).then((recent) => {
      if (stop) return;
      take(recent, false);
      const source = new EventSource(`/api/v1/projects/${projectId}/field/stream?after=${cursor.current}`);
      es = source;
      source.addEventListener("run_event", (m) => take([JSON.parse((m as MessageEvent).data) as Ev], true));
      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED && !poll) {
          poll = setInterval(() => {
            get<Ev[]>(`/projects/${projectId}/field/events?after=${cursor.current}`).then(
              (list) => take(list, true),
              () => undefined, // no signal or a restart: the next poll tries again
            );
          }, 15_000);
        }
      };
    });
    return () => {
      stop = true;
      es?.close();
      if (poll) clearInterval(poll);
      if (pending) clearTimeout(pending);
    };
  }, [projectId, enabled]);
  return events;
}

export function FieldTab({ projectId, stage }: { projectId: string; stage: string }) {
  const { can } = useMe();
  const base = `/projects/${projectId}/field`;
  const summary = useData<S["SummaryOut"]>(`${base}/summary`);
  const runs = useData<S["RunOut"][]>(`${base}/runs`);
  const members = useData<S["MemberOut"][]>(`/projects/${projectId}/members`);
  const { busy, run } = useAction();
  const started = (summary.data?.total ?? 0) > 0;
  const events = useLiveEvents(projectId, started, () => {
    summary.reload();
    runs.reload();
  });
  const name = (id: string | null) => members.data?.find((m) => m.user_id === id)?.full_name ?? "Someone";
  const runRef = (id: string) => runs.data?.find((r) => r.id === id)?.task_ref ?? "";

  if (summary.error) return <Notice tone="bad">{summary.error}</Notice>;
  if (!summary.data) return <Skeleton lines={6} />;
  const s = summary.data;

  if (!started) {
    const ready = stage === "field_work";
    return (
      <div className="section">
        <Empty
          title="Field work has not started"
          action={
            can("field:manage") && (
              <button
                className="btn primary"
                disabled={busy || !ready}
                onClick={async () => {
                  await run(() => post(`${base}/start`, {}, { idem: true }), "Field work started. Engineers were told.");
                  summary.reload();
                  runs.reload();
                }}
              >
                Start field work
              </button>
            )
          }
        >
          {ready
            ? "Starting turns every task of the locked plan into work for its engineer and sends each one their list."
            : "Field work opens once the implementation plan is locked and its stage is approved."}
        </Empty>
      </div>
    );
  }

  const attention = [
    ...s.blocked.map((r) => ({ r, why: `Blocked: ${r.block_reason ?? ""}`, tone: "bad" as const })),
    ...s.failing_checks.map((r) => ({ r, why: "Configuration check failed", tone: "warn" as const })),
    ...s.late.map((r) => ({ r, why: `Not started, planned ${dateTime(r.planned_start)}`, tone: "warn" as const })),
    ...s.overdue
      .filter((r) => !s.late.some((l) => l.id === r.id))
      .map((r) => ({ r, why: `Past its planned end, ${dateTime(r.planned_end)}`, tone: "warn" as const })),
  ];

  return (
    <>
      <div className="section">
        <div className="row between">
          <h2>Field work</h2>
          <span className="muted small">
            {Math.round(s.closed_share * 100)} percent closed. Sent back {s.rework} time{s.rework === 1 ? "" : "s"} in all.
          </span>
        </div>
        <StateTrace counts={s.counts} total={s.total} />
      </div>

      <div className="section">
        <h2>Needs attention</h2>
        {attention.length === 0 ? (
          <p className="muted">Nothing is blocked, late or failing.</p>
        ) : (
          <table className="table">
            <tbody>
              {attention.map(({ r, why, tone }) => (
                <tr key={`${r.id}-${why}`}>
                  <td data-label="Task">
                    <Link href={`/field/${r.id}`}>
                      <span className="mono">{r.task_ref}</span> {r.title}
                    </Link>
                  </td>
                  <td data-label="Why">
                    <Badge tone={tone}>{why}</Badge>
                  </td>
                  <td data-label="Engineer">{name(r.assignee_id)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid2">
        <div className="section">
          <h2>All tasks</h2>
          {runs.data && (
            <table className="table">
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td data-label="Task">
                      <Link href={`/field/${r.id}`}>
                        <span className="mono">{r.task_ref}</span> {r.title}
                      </Link>
                      <div className="muted small">{name(r.assignee_id)}</div>
                    </td>
                    <td className="right" data-label="State">
                      <Badge tone={stateTone(r.state)}>{STATE_SHORT[r.state]}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="section">
          <h2>Live</h2>
          {events.length === 0 ? (
            <p className="muted">Changes appear here as engineers work.</p>
          ) : (
            <ul className="feed" aria-live="polite">
              {events.map((e) => (
                <li key={e.seq} className={e.fresh ? "fresh" : undefined}>
                  <time dateTime={e.at}>{dateTime(e.captured_at ?? e.at).split(", ").pop()}</time>
                  <span>
                    <span className="mono">{runRef(e.run_id)}</span> {e.action.replace(/_/g, " ")}
                    {e.to_state && e.to_state !== e.from_state ? `, now ${STATE_SHORT[e.to_state] ?? e.to_state}` : ""}
                    {e.actor_id ? ` by ${name(e.actor_id)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}
