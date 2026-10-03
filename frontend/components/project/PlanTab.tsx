"use client";
import { useState } from "react";
import { dateTime, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, useAction } from "@/components/ui";

const hours = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`);
const tomorrow = () => new Date(Date.now() + 86_400_000).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

export function PlanTab({ projectId }: { projectId: string }) {
  const { can } = useMe();
  const base = `/projects/${projectId}/plan`;
  const plan = useData<S["PlanDetailOut"] | null>(base);
  const members = useData<S["MemberOut"][]>(`/projects/${projectId}/members`);
  const { busy, run } = useAction();
  const [start, setStart] = useState(tomorrow());
  const [win, setWin] = useState({ from: "", to: "", note: "" });

  if (plan.error) return <Notice tone="bad">{plan.error}</Notice>;
  if (plan.loading && plan.data === null) return <Skeleton lines={6} />;
  const name = (id: string | null | undefined) => members.data?.find((m) => m.user_id === id)?.full_name ?? "Not assigned";
  const d = plan.data;
  const locked = d?.plan.status === "baselined";
  const scheduled = !!d && d.tasks.length > 0 && d.tasks.every((t) => t.start_at);

  if (!d) {
    return (
      <div className="section">
        <Empty
          title="No plan yet"
          action={
            can("plan:write") && (
              <button
                className="btn primary"
                disabled={busy}
                onClick={async () => {
                  await run(() => post(`${base}/generate`, {}), "Plan drafted from the accepted BOQ");
                  plan.reload();
                }}
              >
                Draft the plan
              </button>
            )
          }
        >
          The plan is drafted from the accepted BOQ: one task per line, in a safe order, with a target configuration for
          every device.
        </Empty>
      </div>
    );
  }

  return (
    <>
      <div className="section">
        <div className="row between">
          <h2>
            Plan {d.plan.number} <span className="muted small">from quotation {d.plan.boq_quote_ref}</span>
          </h2>
          <Badge tone={locked ? "ok" : "warn"}>{locked ? "Locked" : "Draft"}</Badge>
        </div>
        <p className="lede">
          {d.tasks.length} tasks, {hours(d.total_minutes)} of work
          {d.ends_at ? `, finishing ${dateTime(d.ends_at)}` : ""}.
        </p>
        {d.plan.warnings.map((w) => (
          <Notice key={w} tone="warn">
            {w}
          </Notice>
        ))}
        <div className="row" style={{ marginTop: 12 }}>
          <a className="btn" href={`/api/v1${base}/render?fmt=pdf`}>
            Download plan (PDF)
          </a>
          <a className="btn quiet" href={`/api/v1${base}/render?fmt=html`} target="_blank" rel="noreferrer">
            Open as a page
          </a>
        </div>
      </div>

      {!locked && can("plan:write") && (
        <div className="section stack">
          <h2>Customer downtime windows</h2>
          <p className="muted">Tasks that stop a device are only placed inside these windows.</p>
          {d.windows.length > 0 && (
            <ul className="small">
              {d.windows.map((w) => (
                <li key={w.id}>
                  {dateTime(w.start_at)} to {dateTime(w.end_at)} {w.note ? `(${w.note})` : ""}
                </li>
              ))}
            </ul>
          )}
          <div className="grid3">
            <Field id="w-from" label="From">
              <input id="w-from" type="datetime-local" value={win.from} onChange={(e) => setWin({ ...win, from: e.target.value })} />
            </Field>
            <Field id="w-to" label="To">
              <input id="w-to" type="datetime-local" value={win.to} onChange={(e) => setWin({ ...win, to: e.target.value })} />
            </Field>
            <Field id="w-note" label="Note">
              <input id="w-note" value={win.note} onChange={(e) => setWin({ ...win, note: e.target.value })} />
            </Field>
          </div>
          <div>
            <button
              className="btn"
              disabled={busy || !win.from || !win.to}
              onClick={async () => {
                await run(
                  () =>
                    post(`${base}/downtime`, {
                      start_at: new Date(win.from).toISOString(),
                      end_at: new Date(win.to).toISOString(),
                      note: win.note || null,
                    }),
                  "Downtime window added",
                );
                setWin({ from: "", to: "", note: "" });
                plan.reload();
              }}
            >
              Add window
            </button>
          </div>

          <h2>Schedule</h2>
          <div className="row">
            <Field id="start" label="First working day">
              <input id="start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <button
              className="btn primary"
              disabled={busy}
              style={{ alignSelf: "end" }}
              onClick={async () => {
                await run(() => post(`${base}/schedule`, { start_date: start, auto_assign: true }), "Scheduled");
                plan.reload();
              }}
            >
              {scheduled ? "Schedule again" : "Schedule the plan"}
            </button>
          </div>
        </div>
      )}

      {!locked && can("plan:baseline") && (
        <div className="section">
          <h2>Lock the plan</h2>
          <p className="muted">
            Locking freezes tasks, dates and target configurations as the stage output. Someone else approves the stage.
          </p>
          <button
            className="btn primary"
            disabled={busy || !scheduled}
            onClick={async () => {
              await run(() => post(`${base}/${d.plan.id}/baseline`, {}, { idem: true }), "Plan locked");
              plan.reload();
            }}
          >
            Lock plan
          </button>
          {!scheduled && <p className="small muted">Schedule every task first.</p>}
        </div>
      )}

      <div className="section">
        <h2>Tasks</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Task</th>
              <th>Engineer</th>
              <th>When</th>
              <th className="right">Time</th>
            </tr>
          </thead>
          <tbody>
            {d.tasks.map((t) => (
              <tr key={t.id}>
                <td data-label="Task">
                  <span className="mono muted">{t.ref}</span> {t.title}
                  <div className="muted small">
                    {t.asset ?? ""}
                    {t.depends_on.length ? ` After ${t.depends_on.join(", ")}.` : ""}
                    {t.requires_downtime ? " Needs downtime." : ""}
                  </div>
                </td>
                <td data-label="Engineer">{name(t.assignee_id)}</td>
                <td data-label="When">{t.start_at ? dateTime(t.start_at) : "Not scheduled"}</td>
                <td className="right num" data-label="Time">
                  {hours(t.minutes)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {d.baselines.length > 0 && (
        <div className="section">
          <h2>Target configuration per device</h2>
          {d.baselines.map((b) => (
            <details key={b.id} style={{ marginBottom: 8 }}>
              <summary>
                {b.device_label} <span className="muted small">({b.device_type})</span>
              </summary>
              <table className="table">
                <tbody>
                  {(b.fields as { key: string; label: string; expected: string; severity: string }[]).map((f) => (
                    <tr key={f.key}>
                      <td data-label="Setting">{f.label}</td>
                      <td data-label="Target">{f.expected}</td>
                      <td data-label="Importance">
                        <Badge tone={f.severity === "critical" ? "bad" : f.severity === "major" ? "warn" : undefined}>{f.severity}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </div>
      )}
    </>
  );
}
