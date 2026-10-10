"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { dateTime, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton, roleLabel } from "@/components/ui";
import { StateTrace } from "@/components/field";
import { Tabs } from "@/components/kit";

type View = "projects" | "bottlenecks" | "engineers";

const dayFmt = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", timeZone: "Asia/Kolkata" });

/** How long each open project has been in its stage, and who it waits on. */
function Bottlenecks() {
  const rows = useData<S["BottleneckOut"][]>("/dashboard/bottlenecks");
  if (rows.error) return <Notice tone="bad">{rows.error}</Notice>;
  if (!rows.data) return <Skeleton lines={6} />;
  if (rows.data.length === 0) return <Empty title="No open projects">Nothing is waiting.</Empty>;
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Project</th>
            <th>Stage</th>
            <th>Days in stage</th>
            <th>Waiting for</th>
          </tr>
        </thead>
        <tbody>
          {rows.data.map((r) => (
            <tr key={r.project_id}>
              <td data-label="Project">
                <Link href={`/projects/${r.project_id}`}>{r.name}</Link>
                <div className="muted small">
                  <span className="mono">{r.code}</span>
                  {r.customer ? `, ${r.customer}` : ""}
                  {r.on_hold ? ", on hold" : ""}
                </div>
              </td>
              <td data-label="Stage">{r.stage_label}</td>
              <td data-label="Days in stage">
                <span className={`health ${r.health}`}>{r.days_in_stage}</span>{" "}
                <span className="muted small">{r.health === "stuck" ? "stuck" : r.health === "slow" ? "slow" : ""}</span>
              </td>
              <td data-label="Waiting for">
                {r.waiting_for === "approval" ? "Approval" : r.waiting_for === "the work" ? "The work" : "The customer"}
                {r.waiting_for !== "the customer to acknowledge" && (
                  <div className="muted small">
                    {r.waiting_on_people.length
                      ? r.waiting_on_people.join(", ")
                      : r.waiting_on_roles.length
                        ? `Nobody on the project is a ${r.waiting_on_roles.map(roleLabel).join(" or ")}`
                        : ""}
                  </div>
                )}
                <div className="muted small">since {dateTime(r.waiting_since)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Each field engineer: open work, and whether the phone holds unsent work, so a quiet task is
 * not mistaken for a stuck one. The project manager also sees the next two weeks. */
function Engineers() {
  const { can } = useMe();
  const status = useData<S["EngineerStatusOut"][]>("/field/engineers");
  const load = useData<S["WorkloadOut"][]>(can("field:manage") ? "/field/workload" : null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => {
      setNow(Date.now());
      void status.reload();
    }, 60_000);
    return () => clearInterval(t);
  }, []);
  if (status.error) return <Notice tone="bad">{status.error}</Notice>;
  if (!status.data) return <Skeleton lines={6} />;
  if (status.data.length === 0) return <Empty title="No field engineers yet">Accounts with the Field engineer role appear here.</Empty>;
  const days = load.data?.[0]?.days ?? [];
  const byUser = new Map((load.data ?? []).map((w) => [w.user_id, w]));
  return (
    <div className="stack">
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Engineer</th>
              <th>Phone</th>
              <th>Open tasks</th>
              <th>Last activity</th>
            </tr>
          </thead>
          <tbody>
            {status.data.map((e) => (
              <tr key={e.user_id}>
                <td data-label="Engineer">{e.full_name}</td>
                <td data-label="Phone">
                  <span className={`state-dot ${e.state}`} aria-hidden="true" />
                  {e.summary}
                </td>
                <td data-label="Open tasks">
                  {e.open_tasks}
                  {e.working_now > 0 && <span className="muted small">, {e.working_now} on site</span>}
                  {e.blocked > 0 && <Badge tone="bad">{e.blocked} blocked</Badge>}
                </td>
                <td data-label="Last activity">{e.last_activity_at ? dateTime(e.last_activity_at) : "None yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        A phone reports its saved work each time it syncs. Offline means no word for 30 minutes. Checked{" "}
        {new Intl.DateTimeFormat("en-IN", { timeStyle: "short", timeZone: "Asia/Kolkata" }).format(now)}.
      </p>
      {load.data && days.length > 0 && (
        <div className="section stack">
          <h2>Next two weeks</h2>
          <p className="muted small">Planned hours per day. Red is more than a working day.</p>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Engineer</th>
                  <th>
                    <div className="workload" aria-hidden="true" style={{ background: "none" }}>
                      {days.map((d) => (
                        <span key={d.day} className="muted small" style={{ background: "none", height: "auto", textAlign: "center" }}>
                          {dayFmt.format(new Date(d.day)).split(" ")[1]}
                        </span>
                      ))}
                    </div>
                  </th>
                  <th>Hours</th>
                </tr>
              </thead>
              <tbody>
                {status.data.map((e) => {
                  const w = byUser.get(e.user_id);
                  if (!w) return null;
                  return (
                    <tr key={e.user_id}>
                      <td data-label="Engineer">
                        {w.full_name}
                        {w.overdue > 0 && <div className="small" style={{ color: "var(--bad)" }}>{w.overdue} overdue</div>}
                      </td>
                      <td data-label="Days">
                        <div className="workload" role="img" aria-label={`${w.full_name}: ${w.hours_next_14_days} hours over 14 days`}>
                          {w.days.map((d) => (
                            <span
                              key={d.day}
                              title={`${d.day}: ${d.tasks} task(s), ${d.hours} h`}
                              data-load={d.hours === 0 ? 0 : d.hours <= 3 ? 1 : d.hours <= 6 ? 2 : d.hours <= 8 ? 3 : 4}
                            />
                          ))}
                        </div>
                      </td>
                      <td data-label="Hours" className="num">
                        {w.hours_next_14_days}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

type Snapshot = {
  counts: Record<string, number>;
  total: number;
  closed_share: number;
  rework: number;
  blocked: { run_id: string; task_ref: string; title: string; reason: string | null }[];
  late: string[];
  overdue: string[];
  failing_checks: string[];
  checkins_today: number;
  planned_end: string | null;
};
type Row = {
  id: string;
  code: string;
  name: string;
  stage: string;
  stage_label: string;
  field: Snapshot | null;
  open_deviations: { critical: number; major: number; minor: number };
  behind_plan: boolean;
};
type Dashboard = {
  generated_at: string;
  totals: Record<
    "projects" | "tasks" | "closed" | "blocked" | "checkins_today" | "open_critical" | "open_major" | "open_minor" | "behind_plan",
    number
  >;
  projects: Row[];
};

/** Projects that need someone first: open critical deviations, blocked work, behind plan. */
const weight = (p: Row) =>
  p.open_deviations.critical * 100 + (p.field?.blocked.length ?? 0) * 10 + (p.behind_plan ? 5 : 0) + p.open_deviations.major;

function Figure({ value, label, tone }: { value: number; label: string; tone?: "bad" | "warn" }) {
  return (
    <div className="figure" data-tone={value > 0 ? tone : undefined}>
      <span className="value">{value}</span>
      <span className="label">{label}</span>
    </div>
  );
}

export default function DashboardPage() {
  const { can } = useMe();
  const [view, setView] = useState<View>(() => {
    if (typeof window === "undefined") return "projects";
    const h = window.location.hash.slice(1);
    return h === "bottlenecks" || h === "engineers" ? h : "projects";
  });
  const d = useData<Dashboard>(can("dashboard:read") ? "/dashboard" : null);
  if (!can("dashboard:read")) return <Notice tone="warn">Your role does not have the dashboard.</Notice>;

  const rows = [...(d.data?.projects ?? [])].sort((a, b) => weight(b) - weight(a));
  const t = d.data?.totals;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Every active project you can see, the ones needing a decision first.</p>
        </div>
        <button className="btn quiet small" onClick={() => d.reload()} disabled={d.loading}>
          {d.loading ? "Refreshing" : "Refresh"}
        </button>
      </div>
      <Tabs
        label="Dashboard"
        tabs={[
          { id: "projects", label: "Projects" },
          { id: "bottlenecks", label: "Waiting on" },
          { id: "engineers", label: "Engineers" },
        ]}
        value={view}
        onChange={(v) => {
          setView(v);
          window.history.replaceState(null, "", v === "projects" ? window.location.pathname : `#${v}`);
        }}
      />
      {view === "bottlenecks" && <Bottlenecks />}
      {view === "engineers" && <Engineers />}
      {view === "projects" && d.error && <Notice tone="bad">{d.error}</Notice>}
      {view === "projects" && !d.data && !d.error && <Skeleton lines={8} />}
      {view === "projects" && t && (
        <div className="figures" aria-label="Across all projects">
          <Figure value={t.open_critical} label="Open critical deviations" tone="bad" />
          <Figure value={t.blocked} label="Tasks blocked" tone="bad" />
          <Figure value={t.behind_plan} label="Projects behind plan" tone="warn" />
          <Figure value={t.checkins_today} label="Check-ins today" />
          <div className="figure wide">
            <span className="value">
              {t.closed}
              <span className="of"> of {t.tasks}</span>
            </span>
            <span className="label">Tasks closed across {t.projects} project{t.projects === 1 ? "" : "s"}</span>
          </div>
        </div>
      )}
      {view === "projects" && d.data && rows.length === 0 && <Empty title="No active projects">Projects you are part of appear here once they start.</Empty>}
      {view === "projects" && rows.length > 0 && (
        <ul className="dash-list">
          {rows.map((p) => {
            const f = p.field;
            const dev = p.open_deviations;
            return (
              <li key={p.id}>
                <div className="dash-head">
                  <Link href={`/projects/${p.id}`} className="title">
                    {p.name}
                  </Link>
                  <span className="mono muted small">{p.code}</span>
                  <span className="grow" />
                  {dev.critical > 0 && <Badge tone="bad">{dev.critical} critical open</Badge>}
                  {dev.major > 0 && <Badge tone="warn">{dev.major} major open</Badge>}
                  {p.behind_plan && <Badge tone="warn">Behind plan</Badge>}
                </div>
                <div className="muted small">{p.stage_label}</div>
                {f && f.total > 0 ? (
                  <>
                    <StateTrace counts={f.counts} total={f.total} />
                    <div className="dash-facts small">
                      <span>{Math.round(f.closed_share * 100)} percent closed</span>
                      {f.checkins_today > 0 && <span>{f.checkins_today} check-in{f.checkins_today === 1 ? "" : "s"} today</span>}
                      {f.rework > 0 && <span>Sent back {f.rework} time{f.rework === 1 ? "" : "s"}</span>}
                      {f.planned_end && <span>Planned to finish {dateTime(f.planned_end)}</span>}
                    </div>
                    {f.blocked.length > 0 && (
                      <ul className="dash-blocked">
                        {f.blocked.map((b) => (
                          <li key={b.run_id}>
                            <Link href={`/field/${b.run_id}`}>
                              <span className="mono">{b.task_ref}</span> {b.title}
                            </Link>
                            : {b.reason ?? "No reason given"}
                          </li>
                        ))}
                      </ul>
                    )}
                    {(f.failing_checks.length > 0 || f.late.length > 0) && (
                      <div className="dash-facts small">
                        {f.failing_checks.length > 0 && <span>Check failing: {f.failing_checks.join(", ")}</span>}
                        {f.late.length > 0 && <span>Not started on time: {f.late.join(", ")}</span>}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="muted small">No field work yet.</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {view === "projects" && d.data && <p className="muted small">Updated {dateTime(d.data.generated_at)}.</p>}
    </>
  );
}
