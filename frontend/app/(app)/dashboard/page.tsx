"use client";
import Link from "next/link";
import { dateTime } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton } from "@/components/ui";
import { StateTrace } from "@/components/field";

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
      {d.error && <Notice tone="bad">{d.error}</Notice>}
      {!d.data && !d.error && <Skeleton lines={8} />}
      {t && (
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
      {d.data && rows.length === 0 && <Empty title="No active projects">Projects you are part of appear here once they start.</Empty>}
      {rows.length > 0 && (
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
      {d.data && <p className="muted small">Updated {dateTime(d.data.generated_at)}.</p>}
    </>
  );
}
