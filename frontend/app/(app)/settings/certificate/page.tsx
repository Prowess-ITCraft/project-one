"use client";
import { useEffect, useState } from "react";
import { dateTime, get, post, put } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Field, Notice, Skeleton, useAction } from "@/components/ui";
import { Check } from "@/components/kit";

type Settings = { wording: string; stamp_uploaded: boolean; stamp_updated_at: string | null };
type Policy = { certificate_blocking: string[]; not_acceptable: string[]; note?: string | null };
const LEVELS = ["critical", "major", "minor"] as const;

function Stamp({ s, reload }: { s: Settings; reload: () => void }) {
  const { can } = useMe();
  const { busy, run } = useAction();
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  useEffect(() => {
    if (!s.stamp_uploaded) return;
    get<{ data_url: string }>("/reporting/settings/stamp")
      .then((r) => setPreview(r.data_url))
      .catch(() => setPreview(null));
  }, [s.stamp_uploaded, s.stamp_updated_at]);

  return (
    <div className="section">
      <h2>IITPL stamp</h2>
      <p className="muted">Printed beside the Director&apos;s name on every certificate. A PNG with a transparent background looks best.</p>
      <div className="stamp-row">
        <div className="stamp-box">
          {preview ? <img src={preview} alt="The IITPL stamp as it prints" /> : <span className="muted small">No stamp yet</span>}
        </div>
        <div className="stack">
          {s.stamp_updated_at && <span className="muted small">Uploaded {dateTime(s.stamp_updated_at)}</span>}
          {!s.stamp_uploaded && <Notice tone="warn">No certificate can be issued until the stamp is uploaded.</Notice>}
          {can("certificate:settings") && (
            <div className="row">
              <input type="file" accept="image/png,image/jpeg" aria-label="Stamp image" onChange={(e) => setFile(e.target.files?.[0] ?? null)} style={{ maxWidth: 300 }} />
              <button
                className="btn primary"
                disabled={!file || busy}
                onClick={async () => {
                  const form = new FormData();
                  form.append("file", file as File);
                  const ok = await run(() => post("/reporting/settings/stamp", undefined, { form }), "Stamp uploaded");
                  if (ok) {
                    setFile(null);
                    reload();
                  }
                }}
              >
                {s.stamp_uploaded ? "Replace stamp" : "Upload stamp"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Wording({ s, reload }: { s: Settings; reload: () => void }) {
  const { can } = useMe();
  const { busy, run } = useAction();
  const [text, setText] = useState(s.wording);
  useEffect(() => setText(s.wording), [s.wording]);
  const editable = can("certificate:settings");
  return (
    <div className="section">
      <h2>Certificate wording</h2>
      <p className="muted">The statement above the customer&apos;s name. Certificates already signed keep the wording they were signed with.</p>
      <Field id="wording" label="Wording" hint={`${text.trim().length} of 600 characters, at least 20.`}>
        <textarea id="wording" value={text} readOnly={!editable} rows={4} onChange={(e) => setText(e.target.value)} />
      </Field>
      {editable && (
        <button
          className="btn"
          disabled={busy || text.trim() === s.wording || text.trim().length < 20 || text.trim().length > 600}
          onClick={async () => {
            const ok = await run(() => put("/reporting/settings/wording", { wording: text }), "Wording saved");
            if (ok) reload();
          }}
        >
          Save wording
        </button>
      )}
    </div>
  );
}

function SeverityPolicy() {
  const { can } = useMe();
  const { busy, run } = useAction();
  const p = useData<Policy>(can("field:read") ? "/verification/policy" : null);
  const [blocking, setBlocking] = useState<string[]>([]);
  useEffect(() => {
    if (p.data) setBlocking(p.data.certificate_blocking);
  }, [p.data]);
  if (!p.data) return null;
  const editable = can("policy:edit");
  const changed = [...blocking].sort().join() !== [...p.data.certificate_blocking].sort().join();
  return (
    <div className="section">
      <h2>What stops a certificate</h2>
      <p className="muted">
        An open deviation of these severities blocks the certificate until it is fixed or waived. Critical always blocks and can never be accepted as it is.
      </p>
      <div className="stack" style={{ margin: "10px 0" }}>
        {LEVELS.map((l) => (
          <Check
            key={l}
            checked={l === "critical" || blocking.includes(l)}
            onChange={(v) => editable && l !== "critical" && setBlocking((b) => (v ? [...b, l] : b.filter((x) => x !== l)))}
          >
            {l[0].toUpperCase() + l.slice(1)}
            {l === "critical" ? ", always" : ""}
          </Check>
        ))}
      </div>
      {editable && (
        <button
          className="btn"
          disabled={busy || !changed}
          onClick={async () => {
            const ok = await run(
              () =>
                put("/verification/policy", {
                  certificate_blocking: Array.from(new Set(["critical", ...blocking])),
                  not_acceptable: p.data?.not_acceptable ?? ["critical"],
                }),
              "Policy saved",
            );
            if (ok) p.reload();
          }}
        >
          Save policy
        </button>
      )}
    </div>
  );
}

export default function CertificateSettings() {
  const { can } = useMe();
  const s = useData<Settings>(can("report:read") ? "/reporting/settings" : null);
  if (!can("report:read")) return <Notice tone="warn">Your role does not see certificate settings.</Notice>;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Certificate</h1>
          <p>How the &ldquo;Certified by IITPL&rdquo; certificate looks, and what must hold before a Director can sign it.</p>
        </div>
      </div>
      {s.error && <Notice tone="bad">{s.error}</Notice>}
      {!s.data && !s.error && <Skeleton lines={6} />}
      {s.data && (
        <>
          <Stamp s={s.data} reload={s.reload} />
          <Wording s={s.data} reload={s.reload} />
          <SeverityPolicy />
        </>
      )}
    </>
  );
}
