"use client";
import { Back } from "@/components/kit";
import { useParams } from "next/navigation";
import { useState } from "react";
import { dateTime, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Field, Notice, Skeleton, useAction } from "@/components/ui";

type Detail = S["ImportDetailOut"];
type FieldRow = {
  path: string;
  status: string;
  message?: string | null;
  source?: string | null;
  required?: boolean;
  raw?: string | null;
};
type Snap = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const humanPath = (p: string) =>
  p
    .replace(/^\//, "")
    .replace(/\[(\w+)\]/g, " $1")
    .replace(/[/_]/g, " ")
    .trim();
const isPointer = (p: string) => /^(\/[A-Za-z0-9_-]+)+$/.test(p);
const tone = (s: string) =>
  s === "conflict" ? "warn" : s === "missing" || s === "unreadable" ? "bad" : s === "corrected" ? "ok" : undefined;

function Score({ label, s }: { label: string; s?: { value?: string | null; out_of?: string; label?: string | null } }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>
        <span className="num">{s?.value ?? "Not read"}</span>
        <span className="muted num"> / {s?.out_of ?? "100"}</span>
        {s?.label && <span className="muted small"> {s.label}</span>}
      </dd>
    </>
  );
}

function Attention({ row, d, reload }: { row: FieldRow; d: Detail; reload: (x?: Detail) => void }) {
  const { busy, run } = useAction();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [value, setValue] = useState("");
  const canConfirm = row.status === "conflict" || !row.required;
  const canSet = isPointer(row.path);

  async function confirm() {
    const r = await run(
      () => post<Detail>(`/prismsuite/imports/${d.id}/resolutions`, { path: row.path, reason, version: d.version }),
      "Field confirmed",
    );
    if (r) reload(r);
  }
  async function setVal() {
    const r = await run(
      () => post<Detail>(`/prismsuite/imports/${d.id}/corrections`, { path: row.path, value, reason, resolves: row.path, version: d.version }),
      "Value saved",
    );
    if (r) reload(r);
  }

  return (
    <tr>
      <td data-label="Field">
        <div>{humanPath(row.path)}</div>
        {row.source && <div className="muted small">{row.source}</div>}
      </td>
      <td data-label="Status">
        <Badge tone={tone(row.status)}>{row.status}</Badge>
        {row.required && <div className="muted small">Required</div>}
      </td>
      <td data-label="What happened">
        <div>{row.message}</div>
        {open && (
          <div className="stack" style={{ marginTop: 10 }}>
            {canSet && (
              <Field id={`v-${row.path}`} label="Correct value">
                <input id={`v-${row.path}`} type="text" value={value} onChange={(e) => setValue(e.target.value)} />
              </Field>
            )}
            <Field id={`r-${row.path}`} label="Reason" hint="Recorded with your name in the audit trail.">
              <input id={`r-${row.path}`} type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <div className="row">
              {canConfirm && (
                <button className="btn primary small" disabled={busy || reason.trim().length < 3} onClick={confirm}>
                  Confirm as it stands
                </button>
              )}
              {canSet && (
                <button className="btn small" disabled={busy || reason.trim().length < 3 || value === ""} onClick={setVal}>
                  Save corrected value
                </button>
              )}
              <button className="btn quiet small" onClick={() => setOpen(false)}>
                Cancel
              </button>
            </div>
            {!canConfirm && !canSet && <p className="muted small">This value cannot be set here. Ask an architect to add a parser fix.</p>}
          </div>
        )}
      </td>
      <td className="right">
        {!open && (
          <button className="btn small" onClick={() => setOpen(true)}>
            Review
          </button>
        )}
      </td>
    </tr>
  );
}

export default function ImportReview() {
  const { id } = useParams<{ id: string }>();
  const { can, me } = useMe();
  const { data, error, reload, loading } = useData<Detail>(`/prismsuite/imports/${id}`);
  const [local, setLocal] = useState<Detail | null>(null);
  const { busy, run } = useAction();
  const [reject, setReject] = useState(false);
  const [note, setNote] = useState("");

  const d = local ?? data;
  if (error && !d) return <Notice tone="bad">{error}</Notice>;
  if (!d) return <Skeleton lines={10} />;

  const snap = d.snapshot as Snap;
  const fields = ((d.read_report as { fields?: FieldRow[] }).fields ?? []) as FieldRow[];
  const attention = fields.filter((f) => ["conflict", "missing", "unreadable"].includes(f.status));
  const open = d.status === "in_review";
  const blockers = attention.filter((f) => f.status === "conflict" || f.required);
  const didWork = d.imported_by === me.id || d.corrections.some((c) => c.corrected_by === me.id);
  const a = snap.assets ?? {};
  const u = snap.upgrades ?? {};
  const sum = (xs: { count?: number }[] | undefined) => (xs ?? []).reduce((n, x) => n + (x.count ?? 0), 0);

  const refresh = (x?: Detail) => {
    if (x) setLocal(x);
    else {
      setLocal(null);
      reload();
    }
  };

  async function approve() {
    await run(() => post(`/prismsuite/imports/${id}/approve`, { note: note || null, version: d!.version }, { idem: true }), "Audit approved and locked");
    refresh();
  }
  async function doReject() {
    const r = await run(() => post(`/prismsuite/imports/${id}/reject`, { reason: note, version: d!.version }), "Report rejected");
    if (r) refresh();
  }

  return (
    <>
      <div className="page-head">
        <div>
          <Back href={`/projects/${d.project_id}`} label="the project" />
          <h1>{snap.header?.customer_name ?? "Audit report"}</h1>
          <p>
            Revision {d.revision}, read by {d.parser_name}
            {snap.header?.report_reference ? `, report ${snap.header.report_reference}` : ""}
          </p>
        </div>
        <Badge tone={d.status === "approved" ? "ok" : d.status === "rejected" ? "bad" : "warn"}>{d.status.replace("_", " ")}</Badge>
      </div>

      <div className="section" style={{ borderTop: 0, paddingTop: 0 }}>
        <h2>What was read</h2>
        <div className="grid2" style={{ marginTop: 12 }}>
          <dl className="kv">
            <Score label="Security" s={snap.scores?.security} />
            <Score label="High availability" s={snap.scores?.high_availability} />
            <Score label="System health" s={snap.scores?.system_health} />
            <Score label="Performance" s={snap.scores?.performance} />
            <Score label="IT structure" s={snap.scores?.it_structure_health} />
          </dl>
          <dl className="kv">
            <dt>Endpoints</dt>
            <dd className="num">
              {a.endpoints_total ?? "Not read"}
              <span className="muted"> ({a.laptops ?? 0} laptops, {a.desktops ?? 0} desktops)</span>
            </dd>
            <dt>Servers, firewalls</dt>
            <dd className="num">
              {a.servers ?? 0}, {a.firewalls ?? 0}
            </dd>
            <dt>Switches, routers</dt>
            <dd className="num">
              {a.switches ?? 0}, {a.routers ?? 0}
            </dd>
            <dt>RAM upgrades</dt>
            <dd className="num">{sum(u.ram)}</dd>
            <dt>Licence upgrades</dt>
            <dd className="num">{sum(u.licence)}</dd>
            <dt>Conflicting antivirus</dt>
            <dd className="num">{(u.conflicting_av ?? []).length}</dd>
            <dt>Vulnerabilities</dt>
            <dd className="num">{snap.vulnerabilities?.total ?? "Not read"}</dd>
          </dl>
        </div>
      </div>

      <div className="section">
        <h2>Needs your attention</h2>
        {attention.length === 0 ? (
          <p className="lede">Every field was read without problems or has been reviewed.</p>
        ) : (
          <>
            <p className="lede">
              {open
                ? "Check each item against the report. Approval stays blocked while a conflict or a required field is open."
                : "These were open when the report was decided."}
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Status</th>
                  <th>What happened</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {attention.map((f) => (
                  <Attention key={f.path} row={f} d={d} reload={refresh} />
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      {d.corrections.length > 0 && (
        <div className="section">
          <h2>Changes made by reviewers</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Reason</th>
                <th className="right">When</th>
              </tr>
            </thead>
            <tbody>
              {d.corrections.map((c) => (
                <tr key={c.id}>
                  <td data-label="Field">{humanPath(c.path)}</td>
                  <td data-label="Reason">{c.reason}</td>
                  <td data-label="When" className="right">
                    {dateTime(c.corrected_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && can("prismsuite:approve") && (
        <div className="section">
          <h2>Decision</h2>
          {didWork && <Notice>You imported this report or changed a value, so someone else has to approve it.</Notice>}
          {blockers.length > 0 && !didWork && (
            <Notice tone="warn">{blockers.length} item(s) above still block approval.</Notice>
          )}
          {!didWork && (
            <div className="stack" style={{ maxWidth: 520, marginTop: 12 }}>
              <Field id="note" label={reject ? "Why is this report being rejected?" : "Note"} hint={reject ? "At least 3 characters." : "Optional"}>
                <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <div className="row">
                {!reject ? (
                  <>
                    <button className="btn primary" disabled={busy || blockers.length > 0} onClick={approve}>
                      Approve and lock
                    </button>
                    <button className="btn" onClick={() => setReject(true)}>
                      Reject report
                    </button>
                  </>
                ) : (
                  <>
                    <button className="btn danger" disabled={busy || note.trim().length < 3} onClick={doReject}>
                      Reject report
                    </button>
                    <button className="btn quiet" onClick={() => setReject(false)}>
                      Cancel
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}
      {loading && null}
    </>
  );
}
