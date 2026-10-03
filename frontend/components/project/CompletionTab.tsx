"use client";
import Link from "next/link";
import { useState } from "react";
import { date, dateTime, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, useAction } from "@/components/ui";
import { Drawer } from "@/components/kit";

/** One release condition as the API states it. Order is the order the work happens in. */
export type Condition = { key: string; label: string; met: boolean; detail: string };
type Waiver = S["WaiverOut"];
type Deviation = S["DeviationOut"];
type Run = S["RunOut"];

const R = "/reporting";

const WAIVER_WORDS: Record<string, string> = {
  requested: "Waiting for the Director",
  approved: "Waiting for the customer",
  acknowledged: "Acknowledged",
  rejected: "Turned down",
};
const waiverTone = (s: string) =>
  s === "acknowledged" ? "ok" : s === "rejected" ? "bad" : ("warn" as const);
const sevTone = (s: string) => (s === "critical" ? "bad" : s === "major" ? "warn" : undefined);

/** What a person does about a condition that is not met yet, and where. */
function nextStep(c: Condition, can: (p: string) => boolean, projectId: string) {
  switch (c.key) {
    case "work":
      return <>Close the remaining tasks in <a href="#field">Field work</a>, or ask for a waiver below.</>;
    case "deviations":
      return <>Fix them on the device and upload a new export, or ask for a waiver below.</>;
    case "waivers":
      return <>The Director decides each request; the customer then confirms by the emailed link.</>;
    case "rescan":
      return <>Import the after-work PrismSuite report as a rescan in <a href="#audit">Audit intake</a>.</>;
    case "stamp":
      return can("certificate:settings") ? (
        <><Link href="/settings/certificate">Upload the IITPL stamp</Link> in certificate settings.</>
      ) : (
        <>A Director or Admin uploads it in certificate settings.</>
      );
    case "report":
      return <>Lock the completion report below once the conditions above are met.</>;
    case "customer":
    case "director":
      return <>Submit the locked report on the <a href={`/projects/${projectId}#overview`}>Overview</a> tab for the customer and the Director.</>;
    default:
      return null;
  }
}

/** The signature of this tab: everything between the project and its certificate, in order. */
function Ledger({ conditions, projectId }: { conditions: Condition[]; projectId: string }) {
  const { can } = useMe();
  const met = conditions.filter((c) => c.met).length;
  const firstOpen = conditions.findIndex((c) => !c.met);
  return (
    <div className="section">
      <div className="row between">
        <h2>Before the certificate</h2>
        <span className="muted small">
          {met} of {conditions.length} met
        </span>
      </div>
      <p className="lede">
        Every line must hold before a Director can sign. Nobody can override one; a task or deviation can only be excused by a waiver the customer accepts.
      </p>
      <ol className="ledger">
        {conditions.map((c, i) => (
          <li key={c.key} data-met={c.met} aria-current={i === firstOpen ? "step" : undefined}>
            <span className="mark" aria-hidden="true" />
            <div>
              <div className="what">
                {c.label}
                <span className="visually-hidden">{c.met ? ", met" : ", not met"}</span>
              </div>
              <div className="detail">{c.detail}</div>
              {!c.met && i === firstOpen && <div className="hint">{nextStep(c, can, projectId)}</div>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function WaiverForm({
  projectId,
  runs,
  deviations,
  onDone,
}: {
  projectId: string;
  runs: Run[];
  deviations: Deviation[];
  onDone: () => void;
}) {
  const { busy, run } = useAction();
  const openRuns = runs.filter((r) => r.state !== "closed");
  const [scope, setScope] = useState<"task" | "deviation">(openRuns.length ? "task" : "deviation");
  const choices =
    scope === "task"
      ? openRuns.map((r) => ({ id: r.id, label: `${r.task_ref} ${r.title}` }))
      : deviations.map((d) => ({ id: d.id, label: `${d.task_ref} ${d.label} (${d.severity})` }));
  const [target, setTarget] = useState("");
  const [kind, setKind] = useState<"deferred_by_customer" | "not_applicable">("deferred_by_customer");
  const [reason, setReason] = useState("");
  const chosen = target && choices.some((c) => c.id === target) ? target : (choices[0]?.id ?? "");

  return (
    <div className="stack">
      <p className="muted">
        A waiver excuses one task or one deviation from the certificate. The Director approves it, then the customer confirms it by email. It is printed on the certificate as an exclusion.
      </p>
      <Field id="w-scope" label="What to excuse">
        <select id="w-scope" value={scope} onChange={(e) => setScope(e.target.value as "task" | "deviation")}>
          <option value="task" disabled={!openRuns.length}>
            A task that will not be done
          </option>
          <option value="deviation" disabled={!deviations.length}>
            A deviation that stays open
          </option>
        </select>
      </Field>
      <Field id="w-target" label={scope === "task" ? "Task" : "Deviation"}>
        <select id="w-target" value={chosen} onChange={(e) => setTarget(e.target.value)}>
          {choices.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </Field>
      <Field id="w-kind" label="Why it is excused">
        <select id="w-kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="deferred_by_customer">The customer moved it to later</option>
          <option value="not_applicable">It does not apply to this site</option>
        </select>
      </Field>
      <Field id="w-reason" label="Reason the customer will read" hint="At least 5 characters. Plain words, no prices.">
        <textarea id="w-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div>
        <button
          className="btn primary"
          disabled={busy || !chosen || reason.trim().length < 5}
          onClick={async () => {
            const ok = await run(
              () => post(`${R}/projects/${projectId}/waivers`, { scope, target_id: chosen, kind, reason }),
              "Waiver requested. The Director decides next.",
            );
            if (ok) onDone();
          }}
        >
          Ask the Director
        </button>
      </div>
    </div>
  );
}

function Waivers({
  projectId,
  waivers,
  runs,
  deviations,
  reload,
}: {
  projectId: string;
  waivers: Waiver[];
  runs: Run[];
  deviations: Deviation[];
  reload: () => void;
}) {
  const { can, me } = useMe();
  const { busy, run } = useAction();
  const [asking, setAsking] = useState(false);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const canAsk = can("report:write") && (runs.some((r) => r.state !== "closed") || deviations.length > 0);

  async function decide(w: Waiver, decision: "approve" | "reject") {
    const ok = await run(
      () => post(`${R}/waivers/${w.id}/decision`, { decision, note: note || null }),
      decision === "approve" ? "Approved. The customer was emailed a link to confirm." : "Turned down",
    );
    if (ok) {
      setRejecting(null);
      setNote("");
      reload();
    }
  }

  return (
    <div className="section">
      <div className="row between">
        <h2>Waivers</h2>
        {canAsk && (
          <button className="btn small" onClick={() => setAsking(true)}>
            Ask for a waiver
          </button>
        )}
      </div>
      {waivers.length === 0 ? (
        <p className="muted">No waivers. Everything in the plan is expected to be done and verified.</p>
      ) : (
        <table className="table">
          <tbody>
            {waivers.map((w) => (
              <tr key={w.id}>
                <td data-label="What">
                  <div>{w.target_label}</div>
                  <div className="muted small">
                    {w.kind === "not_applicable" ? "Does not apply" : "Moved to later by the customer"}: {w.reason}
                  </div>
                  {rejecting === w.id && (
                    <div className="stack" style={{ marginTop: 10 }}>
                      <Field id={`n-${w.id}`} label="Why it is turned down" hint="The team sees this.">
                        <textarea id={`n-${w.id}`} value={note} onChange={(e) => setNote(e.target.value)} />
                      </Field>
                      <div className="row">
                        <button className="btn danger small" disabled={busy || note.trim().length < 5} onClick={() => decide(w, "reject")}>
                          Turn down
                        </button>
                        <button className="btn quiet small" onClick={() => setRejecting(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </td>
                <td data-label="Status">
                  <Badge tone={waiverTone(w.status)}>{WAIVER_WORDS[w.status] ?? w.status}</Badge>
                  <div className="muted small">
                    {w.status === "approved" && w.sent_to ? `Sent to ${w.sent_to}` : ""}
                    {w.status === "acknowledged" ? `${w.acknowledged_name}, ${date(w.acknowledged_at)}` : ""}
                    {w.status === "rejected" && w.decision_note ? w.decision_note : ""}
                  </div>
                </td>
                <td className="right" data-label="">
                  {w.status === "requested" && can("waiver:approve") && w.requested_by !== me.id && rejecting !== w.id && (
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="btn primary small" disabled={busy} onClick={() => decide(w, "approve")}>
                        Approve
                      </button>
                      <button className="btn small" disabled={busy} onClick={() => setRejecting(w.id)}>
                        Turn down
                      </button>
                    </div>
                  )}
                  {w.status === "requested" && w.requested_by === me.id && (
                    <span className="muted small">You asked; someone else decides.</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {asking && (
        <Drawer title="Ask for a waiver" onClose={() => setAsking(false)}>
          <WaiverForm
            projectId={projectId}
            runs={runs}
            deviations={deviations}
            onDone={() => {
              setAsking(false);
              reload();
            }}
          />
        </Drawer>
      )}
    </div>
  );
}

function Deviations({ deviations, reload }: { deviations: Deviation[]; reload: () => void }) {
  const { can } = useMe();
  const { busy, run } = useAction();
  const [accepting, setAccepting] = useState<string | null>(null);
  const [note, setNote] = useState("");
  return (
    <div className="section">
      <h2>Open deviations</h2>
      {deviations.length === 0 ? (
        <p className="muted">Every setting matches its target, or was accepted or waived.</p>
      ) : (
        <table className="table">
          <tbody>
            {deviations.map((d) => (
              <tr key={d.id}>
                <td data-label="Setting">
                  <span className="mono">{d.task_ref}</span> {d.label}
                  <div className="muted small">
                    {d.device ? `${d.device}. ` : ""}
                    {d.actual ? `Found ${d.actual}, target ${d.expected ?? "not set"}.` : d.reason}
                  </div>
                  {accepting === d.id && (
                    <div className="stack" style={{ marginTop: 10 }}>
                      <Field id={`a-${d.id}`} label="Why it can stay as it is" hint="Recorded on the completion report.">
                        <textarea id={`a-${d.id}`} value={note} onChange={(e) => setNote(e.target.value)} />
                      </Field>
                      <div className="row">
                        <button
                          className="btn small"
                          disabled={busy || note.trim().length < 5}
                          onClick={async () => {
                            const ok = await run(() => post(`/verification/deviations/${d.id}/accept`, { note }), "Accepted");
                            if (ok) {
                              setAccepting(null);
                              setNote("");
                              reload();
                            }
                          }}
                        >
                          Accept it
                        </button>
                        <button className="btn quiet small" onClick={() => setAccepting(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </td>
                <td data-label="Severity">
                  <Badge tone={sevTone(d.severity)}>{d.severity}</Badge>
                </td>
                <td className="right" data-label="">
                  {can("field:verify") && d.severity !== "critical" && accepting !== d.id && (
                    <button className="btn quiet small" onClick={() => setAccepting(d.id)}>
                      Accept
                    </button>
                  )}
                  {d.severity === "critical" && <span className="muted small">Must be fixed</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ReportAndCertificate({
  projectId,
  conditions,
  reload,
}: {
  projectId: string;
  conditions: Condition[];
  reload: () => void;
}) {
  const { can, me } = useMe();
  const { busy, run } = useAction();
  const reports = useData<S["ReportOut"][]>(`${R}/projects/${projectId}/reports`);
  const certs = useData<S["CertificateOut"][]>(`${R}/projects/${projectId}/certificates`);
  const [revoking, setRevoking] = useState(false);
  const [reason, setReason] = useState("");
  const isDirector = me.roles.includes("director");
  const reportReady = conditions
    .filter((c) => ["work", "deviations", "waivers", "rescan", "stamp"].includes(c.key))
    .every((c) => c.met);
  const allMet = conditions.every((c) => c.met);
  const valid = certs.data?.find((c) => c.status === "valid");
  const revoked = (certs.data ?? []).filter((c) => c.status === "revoked");

  return (
    <div className="grid2">
      <div className="section">
        <h2>Completion report</h2>
        <p className="muted">
          Work delivered, exclusions, before and after scores, configuration checks and deviations. No prices.
        </p>
        <div className="row" style={{ margin: "12px 0" }}>
          <a className="btn" href={`/api/v1${R}/projects/${projectId}/report/preview?fmt=html`} target="_blank" rel="noreferrer">
            Preview
          </a>
          {can("report:write") && (
            <button
              className="btn primary"
              disabled={busy || !reportReady}
              title={reportReady ? undefined : "The conditions above the report line come first"}
              onClick={async () => {
                const ok = await run(() => post(`${R}/projects/${projectId}/reports`, {}, { idem: true }), "Report locked");
                if (ok) {
                  reports.reload();
                  reload();
                }
              }}
            >
              {reports.data?.length ? "Lock a new version" : "Lock the report"}
            </button>
          )}
        </div>
        {reports.loading && !reports.data && <Skeleton lines={2} />}
        {reports.data && reports.data.length > 0 && (
          <ul className="doclist">
            {[...reports.data].reverse().map((r) => (
              <li key={r.id}>
                <a href={`/api/v1${R}/reports/${r.id}/pdf`}>Completion report {r.number}</a>
                <span className="muted small">Locked {dateTime(r.locked_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="section">
        <h2>Certificate</h2>
        {valid ? (
          <div className="stack">
            <div className="certline">
              <span className="mono">{valid.number}</span>
              <Badge tone="ok">Valid</Badge>
            </div>
            <p className="muted small">Signed {dateTime(valid.issued_at)}. Fingerprint {valid.payload_sha256.slice(0, 16)}.</p>
            <div className="row">
              <a className="btn primary" href={`/api/v1${R}/certificates/${valid.id}/pdf`}>
                Download PDF
              </a>
              <Link className="btn" href={`/verify/${valid.number}`} target="_blank">
                Public check page
              </Link>
              {can("certificate:issue") && !revoking && (
                <button className="btn quiet" onClick={() => setRevoking(true)}>
                  Revoke
                </button>
              )}
            </div>
            {revoking && (
              <div className="stack">
                <Field id="rv" label="Why it is revoked" hint="Shown on the public check page as revoked. The reason stays internal.">
                  <textarea id="rv" value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
                <div className="row">
                  <button
                    className="btn danger"
                    disabled={busy || reason.trim().length < 5}
                    onClick={async () => {
                      const ok = await run(() => post(`${R}/certificates/${valid.id}/revoke`, { reason }), "Certificate revoked");
                      if (ok) {
                        setRevoking(false);
                        setReason("");
                        certs.reload();
                      }
                    }}
                  >
                    Revoke certificate
                  </button>
                  <button className="btn quiet" onClick={() => setRevoking(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <Empty title={allMet ? "Ready to sign" : "Not ready to sign"}>
            {allMet
              ? isDirector
                ? "Every condition holds. Signing fixes its contents for good and gives it a public check page."
                : "Every condition holds. A Director signs it."
              : "The certificate opens once every line of the list above holds."}
          </Empty>
        )}
        {!valid && can("certificate:issue") && (
          <div style={{ marginTop: 12 }}>
            <button
              className="btn primary"
              disabled={busy || !allMet || !isDirector}
              onClick={async () => {
                const ok = await run(() => post(`${R}/projects/${projectId}/certificates`, {}, { idem: true }), "Certificate signed");
                if (ok) {
                  certs.reload();
                  reload();
                }
              }}
            >
              Sign the certificate
            </button>
            {!isDirector && <p className="muted small">Only a Director signs the certificate.</p>}
          </div>
        )}
        {revoked.length > 0 && (
          <ul className="doclist" style={{ marginTop: 14 }}>
            {revoked.map((c) => (
              <li key={c.id}>
                <span className="mono">{c.number}</span>
                <span className="muted small">
                  Revoked {date(c.revoked_at)}: {c.revoke_reason}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function CompletionTab({ projectId, stage }: { projectId: string; stage: string }) {
  const { can } = useMe();
  const { busy, run } = useAction();
  const conditions = useData<Condition[]>(`${R}/projects/${projectId}/conditions`);
  const waivers = useData<Waiver[]>(`${R}/projects/${projectId}/waivers`);
  const runs = useData<Run[]>(can("field:read") ? `/projects/${projectId}/field/runs` : null);
  const devs = useData<Deviation[]>(can("field:read") ? `/verification/projects/${projectId}/deviations?status=open` : null);
  const reloadAll = () => {
    conditions.reload();
    waivers.reload();
    runs.reload();
    devs.reload();
  };

  if (!can("report:read")) return <Notice>Your role does not see the completion report.</Notice>;
  if (conditions.error) return <Notice tone="bad">{conditions.error}</Notice>;
  if (!conditions.data) return <Skeleton lines={8} />;
  const c = conditions.data;
  const fieldDone = c.filter((x) => ["work", "deviations", "waivers"].includes(x.key)).every((x) => x.met);

  return (
    <>
      {stage === "field_work" && can("report:write") && (
        <div className="callout">
          <div>
            <b>{fieldDone ? "Field work is finished" : "Field work is still going"}</b>
            <p className="muted small">
              {fieldDone
                ? "Lock the field work summary, then submit the stage on the Overview tab."
                : "When every task is closed or waived and no blocking deviation is open, lock the summary here."}
            </p>
          </div>
          <button
            className="btn primary"
            disabled={busy || !fieldDone}
            onClick={async () => {
              const ok = await run(
                () => post(`${R}/projects/${projectId}/field-summary`, {}, { idem: true }),
                "Field work summary locked. Submit the stage on the Overview tab.",
              );
              if (ok) reloadAll();
            }}
          >
            Lock field work summary
          </button>
        </div>
      )}
      <Ledger conditions={c} projectId={projectId} />
      <Deviations deviations={devs.data ?? []} reload={reloadAll} />
      <Waivers projectId={projectId} waivers={waivers.data ?? []} runs={runs.data ?? []} deviations={devs.data ?? []} reload={reloadAll} />
      <ReportAndCertificate projectId={projectId} conditions={c} reload={reloadAll} />
    </>
  );
}
