"use client";
import { useEffect, useRef, useState } from "react";
import { dateTime, money, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Tabs } from "@/components/kit";
import { Badge, Empty, Notice, Skeleton, useAction } from "@/components/ui";

type LibFile = S["LibraryFileOut"];
type Dataset = S["DatasetOut"];
type Doc = S["CorpusDocOut"];
type Held = S["QuarantineOut"];

const KIND: Record<string, string> = { boq: "Old BOQ", audit: "PrismSuite report", unknown: "Not recognised" };
const COLLECTION: Record<string, string> = {
  historical_boq_lines: "Historical BOQ lines",
  audit_findings: "Audit findings",
};
const STATUS: Record<string, string> = {
  queued: "Waiting",
  processed: "Read",
  needs_review: "Needs a person",
  skipped: "Skipped",
  failed: "Failed",
};
/** Gap types in plain words; the keys match the BOQ templates. */
const GAP: Record<string, string> = {
  conflicting_av: "Sanitization",
  no_unified_eps: "Endpoint security",
  server_xdr: "Server protection",
  unmanaged_switch: "Managed switch",
  firewall_underconfigured: "Firewall",
  backup_at_risk: "NAS and backup",
  no_disaster_recovery: "Disaster recovery",
  server_not_hardened: "Server hardening",
  underspec_hardware: "Hardware upgrade",
  outdated_licence: "Office licence",
  os_end_of_support: "Operating system",
  no_second_dc: "Server for AD/DC",
  no_dlp: "Data loss prevention",
  other: "Not labelled",
};
const gap = (k: string) => GAP[k] ?? k.replace(/_/g, " ");

function statusTone(s: string) {
  if (s === "processed") return "ok" as const;
  if (s === "failed") return "bad" as const;
  if (s === "needs_review") return "warn" as const;
  return undefined;
}
const scoreTone = (n: number) => (n >= 85 ? "ok" : n >= 70 ? "warn" : "bad");
const kb = (n: number) => (n >= 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

type Analysis = {
  corpus: {
    documents: number;
    original_bytes: number;
    gzip_bytes: number;
    saved_share: number;
    low_quality: { id: string; name: string; kind: string; score: number; issues: string[] }[];
    cleaning_version: string;
  };
  boq: {
    lines: number;
    labels: Record<string, number>;
    unlabelled_share: number;
    bands: {
      gap_type: string;
      line_role: string;
      lines: number;
      customers: number;
      quotes: number;
      typical_qty: number | null;
      price_p25: string | null;
      price_median: string | null;
      price_p75: string | null;
      enough_for_outliers: boolean;
    }[];
    outliers: { gap_type: string; line_role: string; component: string; quote_ref: string; value: string; median: string }[];
  };
};

/* ---------------------------------------------------------------- held rows */

function HeldRows({ dataset, onDone }: { dataset: Dataset; onDone: () => void }) {
  const held = useData<Held[]>(`/datasets/${dataset.id}/quarantine`);
  const { busy, run } = useAction();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const open = (held.data ?? []).filter((h) => h.status === "open");
  if (!held.data || open.length === 0) return null;
  return (
    <div className="section">
      <h2>Lines waiting for a person</h2>
      <p className="muted">
        The reader was not sure about these lines. Check the text against the original, correct it if needed, and confirm.
      </p>
      <table className="table">
        <tbody>
          {open.map((h) => {
            const raw = h.raw as Record<string, string | number | null>;
            const value = edits[h.id] ?? String(raw.component ?? "");
            return (
              <tr key={h.id}>
                <td data-label="Line">
                  <div className="muted small">
                    {String(raw.source_name ?? "")}, line {String(raw.line_ref ?? h.row_index)}
                  </div>
                  <label className="small" htmlFor={`h-${h.id}`}>
                    Component
                  </label>
                  <input id={`h-${h.id}`} value={value} onChange={(e) => setEdits({ ...edits, [h.id]: e.target.value })} />
                  <div className="muted small">{h.errors.join(" ")}</div>
                </td>
                <td className="right" data-label="Amount">
                  {raw.qty ?? ""} x {raw.unit_price ? money(raw.unit_price) : ""}
                </td>
                <td className="right">
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button
                      className="btn primary small"
                      disabled={busy || value.trim().length < 2}
                      onClick={async () => {
                        await run(
                          () => post(`/datasets/${dataset.id}/quarantine/${h.id}`, { action: "fix", values: { component: value.trim() } }),
                          "Line confirmed and added",
                        );
                        held.reload();
                        onDone();
                      }}
                    >
                      Confirm
                    </button>
                    <button
                      className="btn quiet small"
                      disabled={busy}
                      onClick={async () => {
                        await run(() => post(`/datasets/${dataset.id}/quarantine/${h.id}`, { action: "discard" }), "Line discarded");
                        held.reload();
                      }}
                    >
                      Discard
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------------------------------------------------------- corpus */

function CorpusDoc({ id, onClose }: { id: string; onClose: () => void }) {
  const r = useData<S["CorpusRecordOut"]>(`/library/corpus/${id}`);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  const rec = r.data?.record as
    | {
        lines?: { line_ref: string; component: string; component_raw: string | null; qty: number; unit_price: string | null; label: { gap_type: string; line_role: string; rule: string }; flags: string[] }[];
        quality: { score: number; parts: Record<string, number>; issues: string[] };
        text: { pages: string[] };
      }
    | undefined;
  return (
    <>
      <div className="drawer-back" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Corpus document">
        <div className="row between">
          <h2>{r.data?.document.name ?? "Document"}</h2>
          <button className="btn quiet small" onClick={onClose}>
            Close
          </button>
        </div>
        {!rec && <Skeleton lines={8} />}
        {rec && r.data && (
          <div className="stack">
            <p className="muted small">
              {kb(r.data.document.original_bytes)} as {r.data.document.file_kind.toUpperCase()}, {kb(r.data.document.gzip_bytes)} as
              corpus JSON. Cleaning version {r.data.document.cleaning_version}.
            </p>
            <div>
              Quality <span className="quality" data-tone={scoreTone(rec.quality.score)}>{rec.quality.score}</span>
              {rec.quality.issues.length > 0 && (
                <ul className="small">
                  {rec.quality.issues.slice(0, 8).map((i) => (
                    <li key={i}>{i}</li>
                  ))}
                </ul>
              )}
            </div>
            {rec.lines && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Label</th>
                    <th className="right">Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {rec.lines.map((l) => (
                    <tr key={l.line_ref}>
                      <td data-label="Line">
                        <span className="mono muted">{l.line_ref}</span> {l.component}
                        {l.component_raw && <div className="muted small">Read as: {l.component_raw}</div>}
                      </td>
                      <td data-label="Label">
                        {gap(l.label.gap_type)}, {l.label.line_role}
                        <div className="muted small">{l.label.rule}</div>
                      </td>
                      <td className="right num" data-label="Qty">
                        {l.qty}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <details>
              <summary>Text read from the file</summary>
              <pre className="codeblock" style={{ whiteSpace: "pre-wrap", maxHeight: 360, overflow: "auto" }}>
                {rec.text.pages.join("\n\n")}
              </pre>
            </details>
          </div>
        )}
      </aside>
    </>
  );
}

function CorpusTab() {
  const docs = useData<Doc[]>("/library/corpus?limit=200");
  const [open, setOpen] = useState<string | null>(null);
  if (docs.error) return <Notice tone="bad">{docs.error}</Notice>;
  if (!docs.data) return <Skeleton lines={5} />;
  if (docs.data.length === 0) return <Empty title="No documents converted yet">Every file added to the library appears here once it is read.</Empty>;
  return (
    <div className="section">
      <p className="muted">
        Each file is read once and kept as compact JSON. Everything else, history hints, analysis and training, works from
        these records.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Document</th>
            <th>Labels</th>
            <th className="right">Size</th>
            <th className="right">Quality</th>
          </tr>
        </thead>
        <tbody>
          {docs.data.map((d) => (
            <tr key={d.id}>
              <td data-label="Document">
                <button className="linklike title" onClick={() => setOpen(d.id)}>
                  {d.name}
                </button>
                <div className="muted small">
                  {KIND[d.kind] ?? d.kind}, {d.lines} {d.kind === "audit" ? "facts" : "lines"}, {dateTime(d.built_at)}
                </div>
              </td>
              <td data-label="Labels">
                <div className="labels">
                  {Object.entries(d.labels).map(([k, n]) => (
                    <Badge key={k} tone={k === "other" ? "warn" : undefined}>
                      {gap(k)} {n}
                    </Badge>
                  ))}
                </div>
              </td>
              <td className="right" data-label="Size">
                <span className="num">{kb(d.original_bytes)}</span>
                <div className="muted small num">{kb(d.gzip_bytes)} stored</div>
              </td>
              <td className="right" data-label="Quality">
                <span className="quality" data-tone={scoreTone(d.quality_score)}>
                  {d.quality_score}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open && <CorpusDoc id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

/* ---------------------------------------------------------------- data quality */

function QualityTab() {
  const { can } = useMe();
  const a = useData<Analysis>("/library/analysis");
  const { busy, run } = useAction();
  if (a.error) return <Notice tone="bad">{a.error}</Notice>;
  if (!a.data) return <Skeleton lines={6} />;
  const { corpus, boq } = a.data;
  const priced = boq.bands.filter((b) => b.price_median);
  const max = Math.max(1, ...priced.map((b) => Number(b.price_p75)));
  return (
    <>
      <div className="section">
        <p className="lede">
          {corpus.documents} document{corpus.documents === 1 ? "" : "s"} in the corpus, {kb(corpus.original_bytes)} of originals kept as{" "}
          {kb(corpus.gzip_bytes)} of data ({Math.round(corpus.saved_share * 100)} percent smaller). {boq.lines} BOQ lines,{" "}
          {Math.round((1 - boq.unlabelled_share) * 100)} percent labelled with a gap type.
        </p>
        {can("dataset:admin") && (
          <button
            className="btn"
            disabled={busy}
            onClick={async () => {
              const r = await run(() => post<S["RebuildOut"]>("/library/rebuild"));
              if (r) a.reload();
            }}
          >
            Read every file again
          </button>
        )}
      </div>

      {corpus.low_quality.length > 0 && (
        <div className="section">
          <h2>Documents to check</h2>
          <table className="table">
            <tbody>
              {corpus.low_quality.map((d) => (
                <tr key={d.id}>
                  <td data-label="Document">
                    {d.name}
                    <div className="muted small">{d.issues.join(" ")}</div>
                  </td>
                  <td className="right" data-label="Quality">
                    <span className="quality" data-tone={scoreTone(d.score)}>
                      {d.score}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="section">
        <h2>What past BOQs say, by gap type</h2>
        {boq.bands.length === 0 ? (
          <p className="muted">Add old BOQs to the library to see typical quantities and prices.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Gap type</th>
                <th className="right">Lines</th>
                <th className="right">Customers</th>
                <th className="right">Typical qty</th>
                <th>Price range (middle half)</th>
              </tr>
            </thead>
            <tbody>
              {boq.bands.map((b) => (
                <tr key={`${b.gap_type}-${b.line_role}`}>
                  <td data-label="Gap type">
                    {gap(b.gap_type)} <span className="muted">{b.line_role}</span>
                  </td>
                  <td className="right num" data-label="Lines">
                    {b.lines}
                  </td>
                  <td className="right num" data-label="Customers">
                    {b.customers}
                  </td>
                  <td className="right num" data-label="Typical qty">
                    {b.typical_qty ?? ""}
                  </td>
                  <td data-label="Price range">
                    {b.price_median ? (
                      <div className="price-cell">
                        <span className="figures">
                          {money(b.price_p25)} to {money(b.price_p75)}, middle {money(b.price_median)}
                        </span>
                        <div className="band" aria-hidden="true">
                          <span
                            className="range"
                            style={{
                              left: `${(Number(b.price_p25) / max) * 100}%`,
                              width: `${Math.max(0.5, ((Number(b.price_p75) - Number(b.price_p25)) / max) * 100)}%`,
                            }}
                          />
                          <span className="median" style={{ left: `${(Number(b.price_median) / max) * 100}%` }} />
                        </div>
                        {!b.enough_for_outliers && <span className="muted small">Too few prices to flag outliers yet.</span>}
                      </div>
                    ) : (
                      <span className="muted small">No prices (summary BOQs)</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="section">
        <h2>Prices far from the usual</h2>
        {boq.outliers.length === 0 ? (
          <p className="muted">None flagged. Each gap type needs at least 5 prices before outliers are judged.</p>
        ) : (
          <table className="table">
            <tbody>
              {boq.outliers.map((o, i) => (
                <tr key={i}>
                  <td data-label="Line">
                    {o.component}
                    <div className="muted small">
                      {gap(o.gap_type)}, quote {o.quote_ref}
                    </div>
                  </td>
                  <td className="right" data-label="Price">
                    {money(o.value)} <div className="muted small">usual {money(o.median)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- page */

export default function Library() {
  const { can } = useMe();
  const files = useData<LibFile[]>(can("dataset:read") ? "/library/files" : null);
  const cols = useData<Record<string, Dataset | null>>(can("dataset:read") ? "/library/collections" : null);
  const { busy, run } = useAction();
  const [over, setOver] = useState(false);
  const [tab, setTab] = useState<"files" | "corpus" | "quality">("files");
  const input = useRef<HTMLInputElement>(null);

  if (!can("dataset:read")) return <Notice tone="warn">You do not have access to the library.</Notice>;

  async function send(list: FileList | File[]) {
    for (const file of Array.from(list)) {
      const form = new FormData();
      form.append("file", file);
      const r = await run(() => post<S["LibraryUploadOut"]>("/library/files", undefined, { form }));
      if (r) await run(async () => undefined, r.duplicate ? `${file.name} was already in the library` : `${file.name} added`);
    }
    files.reload();
    cols.reload();
  }

  const reading = (files.data ?? []).some((f) => f.status === "queued");
  const boqSet = cols.data?.historical_boq_lines ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p>
            Old BOQs and PrismSuite reports. Each file is read once, cleaned, labelled and kept as compact data for
            suggestions and, later, training.
          </p>
        </div>
      </div>

      {can("dataset:write") && (
        <div
          className="drop"
          data-over={over}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            void send(e.dataTransfer.files);
          }}
        >
          <p>
            <strong>Drop files here</strong>, or{" "}
            <button className="btn small" disabled={busy} onClick={() => input.current?.click()}>
              choose files
            </button>
          </p>
          <p className="stepnote">
            BOQ as PDF or Excel. PrismSuite report as Word or JSON. The same file is never added twice. Many files at once?
            Copy them into the inbox folder on the server.
          </p>
          <input
            ref={input}
            type="file"
            multiple
            hidden
            accept=".pdf,.xlsx,.docx,.json"
            aria-label="Library files"
            onChange={(e) => e.target.files && void send(e.target.files)}
          />
        </div>
      )}

      <Tabs
        label="Library sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "files", label: "Files", count: files.data?.filter((f) => f.status === "needs_review").length, attention: true },
          { id: "corpus", label: "Corpus" },
          { id: "quality", label: "Data quality" },
        ]}
      />

      {tab === "files" && (
        <>
          {boqSet && <HeldRows dataset={boqSet} onDone={() => files.reload()} />}
          <div className="section">
            <h2>Files</h2>
            {reading && (
              <p className="small muted">
                Some files are still being read.{" "}
                <button className="btn quiet small" onClick={() => files.reload()}>
                  Refresh
                </button>
              </p>
            )}
            {files.loading && !files.data && <Skeleton lines={4} />}
            {files.data && files.data.length === 0 && (
              <Empty title="The library is empty">Drop a finished BOQ or an audit report above and it will show here with what was read.</Empty>
            )}
            {files.data && files.data.length > 0 && (
              <table className="table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Kind</th>
                    <th>Status</th>
                    <th className="right">Added to data</th>
                    <th className="right">Held</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {files.data.map((f) => (
                    <tr key={f.id}>
                      <td data-label="File">
                        <div className="title">{f.original_name}</div>
                        {f.message && <div className="muted small">{f.message}</div>}
                      </td>
                      <td data-label="Kind">{f.kind ? (KIND[f.kind] ?? f.kind) : "Not read yet"}</td>
                      <td data-label="Status">
                        <Badge tone={statusTone(f.status)}>{STATUS[f.status] ?? f.status}</Badge>
                      </td>
                      <td data-label="Added to data" className="right num">
                        {f.rows_added}
                      </td>
                      <td data-label="Held" className="right num">
                        {f.rows_held}
                      </td>
                      <td className="right">
                        {can("dataset:write") && (f.status === "failed" || f.status === "skipped") && (
                          <button
                            className="btn quiet small"
                            disabled={busy}
                            onClick={async () => {
                              await run(() => post(`/library/files/${f.id}/retry`), "Reading again");
                              files.reload();
                            }}
                          >
                            Try again
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="section">
            <h2>Collections</h2>
            <table className="table">
              <tbody>
                {Object.entries(cols.data ?? {}).map(([key, d]) => (
                  <tr key={key}>
                    <td data-label="Collection">{COLLECTION[key] ?? key}</td>
                    <td className="right muted" data-label="Version">
                      {d ? `Version ${d.latest_version}` : "Nothing added yet"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {tab === "corpus" && <CorpusTab />}
      {tab === "quality" && <QualityTab />}
    </>
  );
}
