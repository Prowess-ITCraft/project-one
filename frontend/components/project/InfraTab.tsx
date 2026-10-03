"use client";
import { useMemo, useState } from "react";
import { ApiError, post, type S } from "@/lib/api";
import { useData, useMe, useToast } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton, roleLabel, useAction } from "@/components/ui";

type State = S["StateOut"];
const LENS: [string, string][] = [
  ["security", "Security"],
  ["resilience", "Resilience"],
  ["productivity", "Productivity"],
  ["health", "Health"],
];
const tone = (v: number | null | undefined) => (v == null ? undefined : v >= 70 ? "ok" : v >= 55 ? "warn" : "bad");

type Anything = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function Lenses({ data }: { data: Anything }) {
  return (
    <div className="lenses">
      {LENS.map(([k, label]) => {
        const v = data.lenses?.[k]?.score as number | null | undefined;
        return (
          <div className="lens" key={k} data-tone={tone(v)}>
            <div className="v">{v == null ? "n/a" : v.toFixed(1)}</div>
            <div className="k">
              {label}
              <div className="muted small">{data.lenses?.[k]?.from}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Current({ s, reload, canWrite }: { s: State; reload: () => void; canWrite: boolean }) {
  const { busy, run } = useAction();
  const d = s.data as Anything;
  const c = (d.components ?? {}) as Anything;
  return (
    <div className="section">
      <div className="row between">
        <h2>Current IT infrastructure</h2>
        <div className="row">
          <Badge tone={s.status === "locked" ? "ok" : "warn"}>{s.status === "locked" ? `Locked v${s.number}` : `Draft v${s.number}`}</Badge>
          {canWrite && s.status === "draft" && (
            <button
              className="btn primary small"
              disabled={busy}
              onClick={async () => {
                await run(() => post(`/projects/${s.project_id}/infra/${s.id}/lock`, undefined, { idem: true }), "Current infrastructure locked");
                reload();
              }}
            >
              Lock as the baseline
            </button>
          )}
        </div>
      </div>
      <p className="stepnote">
        Built from the approved audit {d.report_reference ? `(${d.report_reference})` : ""}. The four lenses come from the
        PrismSuite scores.
      </p>
      <Lenses data={d} />
      <table className="table">
        <thead>
          <tr>
            <th>Component</th>
            <th>What the audit found</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td data-label="Component">Endpoints</td>
            <td data-label="What the audit found">
              <span className="num">{c.endpoints?.count ?? "n/a"}</span> systems.{" "}
              <span className="num">{c.endpoints?.multi_av?.length ?? 0}</span> run more than one antivirus,{" "}
              <span className="num">{c.endpoints?.ram_low?.length ?? 0}</span> need more memory,{" "}
              <span className="num">{c.endpoints?.office_old?.length ?? 0}</span> have an old Office.
              {c.endpoints?.eps_coverage != null && <> EPS on {Math.round(c.endpoints.eps_coverage * 100)}%.</>}
            </td>
          </tr>
          {(["servers", "firewalls", "nas", "switches", "routers"] as const).map((k) => (
            <tr key={k}>
              <td data-label="Component">{roleLabel(k)}</td>
              <td data-label="What the audit found">
                {(c[k] as Anything[] | undefined)?.length ? (
                  (c[k] as Anything[]).map((x, i) => (
                    <div key={i}>
                      {x.brand_model}
                      {x.managed === false && <Badge tone="warn">unmanaged</Badge>}{" "}
                      {x.storage_used_percent && <span className="muted">{x.storage_used_percent}% used</span>}
                    </div>
                  ))
                ) : (
                  <span className="muted">None in the audit</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.unknown_facts?.length > 0 && (
        <p className="stepnote" style={{ marginTop: 10 }}>
          {d.unknown_facts.length} facts are not in the audit (for example a blank backup schedule). They become items to
          verify on site, never guesses.
        </p>
      )}
    </div>
  );
}

function Ideal({ s, reload, canWrite }: { s: State; reload: () => void; canWrite: boolean }) {
  const { busy, run } = useAction();
  const d = s.data as Anything;
  const [comp, setComp] = useState("all");
  const targets = (d.targets ?? []) as Anything[];
  const shown = useMemo(() => targets.filter((t) => comp === "all" || t.component === comp), [targets, comp]);
  const comps = Array.from(new Set(targets.map((t) => t.component as string)));
  return (
    <div className="section">
      <div className="row between">
        <h2>Ideal IT infrastructure</h2>
        <div className="row">
          <Badge tone={s.status === "locked" ? "ok" : "warn"}>{s.status === "locked" ? `Locked v${s.number}` : `Draft v${s.number}`}</Badge>
          {canWrite && s.status === "draft" && (
            <button
              className="btn primary small"
              disabled={busy}
              onClick={async () => {
                await run(() => post(`/projects/${s.project_id}/infra/${s.id}/lock`, undefined, { idem: true }), "Ideal infrastructure locked");
                reload();
              }}
            >
              Lock as the target
            </button>
          )}
        </div>
      </div>
      <p className="stepnote">
        The rules that apply to a {d.tier?.company_size} company on the {d.tier?.budget_tier} tier:{" "}
        <span className="num">{d.summary?.met}</span> met, <span className="num">{d.summary?.not_met}</span> not met,{" "}
        <span className="num">{d.summary?.unknown}</span> to verify.
      </p>
      <div className="filters" style={{ marginTop: 10 }}>
        <select aria-label="Component" value={comp} onChange={(e) => setComp(e.target.value)}>
          <option value="all">All components</option>
          {comps.map((c) => (
            <option key={c} value={c}>
              {roleLabel(c)}
            </option>
          ))}
        </select>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Target</th>
            <th>Lens</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t) => (
            <tr key={t.code}>
              <td data-label="Target">
                <div>{t.target}</div>
                <div className="muted small">
                  {t.title} <span className="mono">{t.code}</span>
                </div>
              </td>
              <td data-label="Lens">{roleLabel(t.lens)}</td>
              <td data-label="Status">
                <Badge tone={t.status === "met" ? "ok" : t.status === "not_met" ? (t.priority === "high" ? "bad" : "warn") : undefined}>
                  {t.status === "met" ? "Met" : t.status === "not_met" ? "Not met" : "To verify"}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InfraTab({ projectId }: { projectId: string }) {
  const { can } = useMe();
  const states = useData<State[]>(can("infra:read") ? `/projects/${projectId}/infra` : null);
  const { busy, run } = useAction();
  const toast = useToast();
  const canWrite = can("infra:write");
  if (!can("infra:read")) return <Notice tone="warn">You do not have access to the infrastructure view.</Notice>;
  if (states.loading && !states.data) return <Skeleton lines={6} />;
  const list = states.data ?? [];
  const current = list.find((s) => s.kind === "current" && s.status !== "superseded");
  const ideal = list.find((s) => s.kind === "ideal" && s.status !== "superseded");

  async function build(kind: "current" | "ideal") {
    try {
      await run(() => post(`/projects/${projectId}/infra/${kind}`), kind === "current" ? "Current infrastructure built" : "Ideal infrastructure built");
    } catch (e) {
      if (e instanceof ApiError) toast(e.message, true);
    }
    states.reload();
  }

  return (
    <>
      {!current && (
        <Empty
          title="No baseline yet"
          action={
            canWrite ? (
              <button className="btn primary" disabled={busy} onClick={() => build("current")}>
                Build from the approved audit
              </button>
            ) : undefined
          }
        >
          The current infrastructure is built from the approved audit, so approve the audit first.
        </Empty>
      )}
      {current && <Current s={current} reload={states.reload} canWrite={canWrite} />}
      {current && canWrite && current.status === "draft" && (
        <button className="btn small" disabled={busy} onClick={() => build("current")}>
          Rebuild from the audit
        </button>
      )}
      {current?.status === "locked" && !ideal && (
        <div className="section">
          <h2>Ideal IT infrastructure</h2>
          <p className="lede">Needs the intake questionnaire, which chooses the rules for this customer.</p>
          {canWrite && (
            <button className="btn primary" disabled={busy} onClick={() => build("ideal")}>
              Build the ideal state
            </button>
          )}
        </div>
      )}
      {ideal && <Ideal s={ideal} reload={states.reload} canWrite={canWrite} />}
      {ideal && canWrite && ideal.status === "draft" && (
        <button className="btn small" disabled={busy} onClick={() => build("ideal")}>
          Rebuild
        </button>
      )}
    </>
  );
}
