"use client";
import { useState } from "react";
import { patch, put, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Field, Notice, Skeleton, useAction } from "@/components/ui";
import { Back, Check, Tabs } from "@/components/kit";

// ------------------------------------------------------------------ BOQ templates

type QtyRule = { rule: "fixed" | "per_fact" | "per_gap" | "per_site" | "expr"; n?: number | null; fact?: string | null; mult?: number; expr?: string | null };
type TLine = {
  key: string;
  role: "supply" | "setup" | "support" | "service" | "licence";
  item_code?: string | null;
  recommend?: { category: string; count: number } | null;
  qty: QtyRule;
  option_group?: string | null;
  section?: string | null;
  note?: string | null;
};
type Template = { id: string; gap_type: string; title: string; lines: TLine[]; active: boolean; revision: number; version: number };

const ROLES: TLine["role"][] = ["supply", "setup", "support", "service", "licence"];
const RULES: { id: QtyRule["rule"]; label: string }[] = [
  { id: "fixed", label: "A fixed number" },
  { id: "per_fact", label: "One per audit count" },
  { id: "per_gap", label: "One per affected item" },
  { id: "per_site", label: "One per site" },
  { id: "expr", label: "A formula" },
];
const FACTS = [
  "endpoint.count",
  "endpoint.multi_av_count",
  "endpoint.ram_low_count",
  "endpoint.office_old_count",
  "endpoint.os_eol_count",
  "server.count",
  "firewall.count",
  "nas.count",
  "switch.total",
  "switch.unmanaged_count",
  "router.count",
  "access_point.count",
];

function qtyWords(q: QtyRule): string {
  if (q.rule === "fixed") return `${q.n ?? 0}`;
  if (q.rule === "per_fact") return `${q.mult && q.mult > 1 ? `${q.mult} x ` : ""}${q.fact ?? "?"}`;
  if (q.rule === "per_gap") return `${q.mult && q.mult > 1 ? `${q.mult} x ` : ""}affected items`;
  if (q.rule === "per_site") return `${q.mult && q.mult > 1 ? `${q.mult} x ` : ""}sites`;
  return q.expr ?? "";
}

function TemplateEditor({ t, onSaved }: { t: Template; onSaved: () => void }) {
  const [title, setTitle] = useState(t.title);
  const [active, setActive] = useState(t.active);
  const [lines, setLines] = useState<TLine[]>(t.lines);
  const { busy, run } = useAction();
  const upd = (i: number, ch: Partial<TLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...ch } : l)));
  const updQty = (i: number, ch: Partial<QtyRule>) => upd(i, { qty: { ...lines[i].qty, ...ch } });
  return (
    <div className="stack">
      <div className="form-grid">
        <Field id={`tt-${t.gap_type}`} label="Title">
          <input id={`tt-${t.gap_type}`} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Check checked={active} onChange={setActive}>
          Used when drafting BOQs
        </Check>
      </div>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Line</th>
              <th>Product</th>
              <th>Quantity</th>
              <th>Option and section</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td data-label="Line">
                  <input aria-label="Line key" value={l.key} onChange={(e) => upd(i, { key: e.target.value.toLowerCase() })} style={{ width: 130 }} />
                  <select aria-label="Role" value={l.role} onChange={(e) => upd(i, { role: e.target.value as TLine["role"] })}>
                    {ROLES.map((r) => (
                      <option key={r}>{r}</option>
                    ))}
                  </select>
                </td>
                <td data-label="Product">
                  <select
                    aria-label="Product from"
                    value={l.recommend ? "recommend" : "item"}
                    onChange={(e) =>
                      upd(i, e.target.value === "recommend" ? { recommend: { category: "", count: 2 }, item_code: null } : { recommend: null, item_code: "" })
                    }
                  >
                    <option value="item">Catalogue code</option>
                    <option value="recommend">Best products in a category</option>
                  </select>
                  {l.recommend ? (
                    <span className="row">
                      <input
                        aria-label="Category"
                        placeholder="category"
                        value={l.recommend.category}
                        onChange={(e) => upd(i, { recommend: { ...l.recommend!, category: e.target.value } })}
                        style={{ width: 120 }}
                      />
                      <select
                        aria-label="How many options"
                        value={l.recommend.count}
                        onChange={(e) => upd(i, { recommend: { ...l.recommend!, count: Number(e.target.value) } })}
                      >
                        {[1, 2, 3].map((n) => (
                          <option key={n} value={n}>
                            {n} option{n > 1 ? "s" : ""}
                          </option>
                        ))}
                      </select>
                    </span>
                  ) : (
                    <input
                      aria-label="Catalogue code"
                      className="mono"
                      value={l.item_code ?? ""}
                      onChange={(e) => upd(i, { item_code: e.target.value.toUpperCase() })}
                      style={{ width: 170 }}
                    />
                  )}
                </td>
                <td data-label="Quantity">
                  <select aria-label="Quantity rule" value={l.qty.rule} onChange={(e) => updQty(i, { rule: e.target.value as QtyRule["rule"] })}>
                    {RULES.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                  {l.qty.rule === "fixed" && (
                    <input aria-label="Number" inputMode="numeric" value={l.qty.n ?? ""} onChange={(e) => updQty(i, { n: Number(e.target.value) || 0 })} style={{ width: 70 }} />
                  )}
                  {l.qty.rule === "per_fact" && (
                    <select aria-label="Audit count" value={l.qty.fact ?? ""} onChange={(e) => updQty(i, { fact: e.target.value })}>
                      <option value="">Choose</option>
                      {FACTS.map((f) => (
                        <option key={f}>{f}</option>
                      ))}
                    </select>
                  )}
                  {l.qty.rule === "expr" && (
                    <input aria-label="Formula" className="mono" value={l.qty.expr ?? ""} onChange={(e) => updQty(i, { expr: e.target.value })} style={{ width: 200 }} />
                  )}
                  {["per_fact", "per_gap", "per_site"].includes(l.qty.rule) && (
                    <input
                      aria-label="Times"
                      title="Times"
                      inputMode="numeric"
                      value={l.qty.mult ?? 1}
                      onChange={(e) => updQty(i, { mult: Math.max(1, Number(e.target.value) || 1) })}
                      style={{ width: 50 }}
                    />
                  )}
                  <div className="muted small">{qtyWords(l.qty)}</div>
                </td>
                <td data-label="Option and section">
                  <input aria-label="Option group" placeholder="option group" value={l.option_group ?? ""} onChange={(e) => upd(i, { option_group: e.target.value || null })} style={{ width: 120 }} />
                  <input aria-label="Section" placeholder="section" value={l.section ?? ""} onChange={(e) => upd(i, { section: e.target.value || null })} style={{ width: 150 }} />
                </td>
                <td>
                  <button className="btn quiet small" disabled={lines.length <= 1} onClick={() => setLines(lines.filter((_, j) => j !== i))}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button
          className="btn"
          disabled={lines.length >= 30}
          onClick={() => setLines([...lines, { key: `line-${lines.length + 1}`, role: "service", item_code: "", qty: { rule: "fixed", n: 1, mult: 1 } }])}
        >
          Add line
        </button>
        <button
          className="btn primary"
          disabled={busy || title.trim().length < 3}
          onClick={async () => {
            const clean = lines.map((l) => ({
              key: l.key,
              role: l.role,
              ...(l.recommend ? { recommend: l.recommend } : { item_code: l.item_code }),
              qty: Object.fromEntries(Object.entries(l.qty).filter(([, v]) => v !== null && v !== undefined && v !== "")),
              ...(l.option_group ? { option_group: l.option_group } : {}),
              ...(l.section ? { section: l.section } : {}),
              ...(l.note ? { note: l.note } : {}),
            }));
            const r = await run(() => put(`/boq/templates/${t.gap_type}`, { title: title.trim(), lines: clean, active, version: t.version }), "Template saved");
            if (r !== undefined) onSaved();
          }}
        >
          Save template
        </button>
      </div>
      <p className="muted small">
        BOQs already drafted keep their lines. A formula uses the audit counts written with an underscore, with + - * /
        and ceil(), floor(), round(), min(), max(), for example ceil(endpoint_count / 10).
      </p>
    </div>
  );
}

function BoqTemplates() {
  const list = useData<Template[]>("/boq/templates");
  const [open, setOpen] = useState<string | null>(null);
  if (list.error) return <Notice tone="bad">{list.error}</Notice>;
  if (!list.data) return <Skeleton lines={6} />;
  return (
    <div className="stack">
      <p className="muted">One template per kind of audit finding: the product and service lines it turns into on a BOQ.</p>
      {list.data.map((t) => (
        <div key={t.gap_type} className="section stack">
          <div className="row between">
            <span>
              <strong>{t.title}</strong> <span className="muted small mono">{t.gap_type}</span>{" "}
              {!t.active && <Badge>Not used</Badge>} <span className="muted small">revision {t.revision}</span>
            </span>
            <button className="btn small" onClick={() => setOpen(open === t.gap_type ? null : t.gap_type)}>
              {open === t.gap_type ? "Close" : "Edit"}
            </button>
          </div>
          {open === t.gap_type ? (
            <TemplateEditor
              key={t.version}
              t={t}
              onSaved={() => {
                setOpen(null);
                void list.reload();
              }}
            />
          ) : (
            <ul className="plain-list small">
              {t.lines.map((l) => (
                <li key={l.key}>
                  <span className="mono">{l.recommend ? `best ${l.recommend.count} in ${l.recommend.category}` : l.item_code}</span>, {l.role}, quantity{" "}
                  {qtyWords(l.qty)}
                  {l.option_group ? `, option group ${l.option_group}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ field task templates

const EVIDENCE_TYPES = ["photo", "screenshot", "config_export", "serial", "note"];

function TaskTemplate({ t, onSaved }: { t: S["TaskTemplateOut"]; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({
    title: t.title,
    minutes_fixed: String(t.minutes_fixed),
    minutes_per_unit: String(t.minutes_per_unit),
    requires_downtime: t.requires_downtime,
    active: t.active,
    steps: t.steps.join("\n"),
  });
  const [evidence, setEvidence] = useState(t.evidence as { type: string; label: string; required: boolean }[]);
  const { busy, run } = useAction();
  return (
    <div className="section stack">
      <div className="row between">
        <span>
          <strong>{t.title}</strong> <span className="muted small mono">{t.key}</span> {!t.active && <Badge>Not used</Badge>}
          <div className="muted small">
            {t.steps.length} steps, {t.evidence.length} pieces of evidence, about {t.minutes_fixed} min
            {t.minutes_per_unit ? ` plus ${t.minutes_per_unit} min each` : ""}
            {t.requires_downtime ? ", needs downtime" : ""}
          </div>
        </span>
        <button className="btn small" onClick={() => setOpen(!open)}>
          {open ? "Close" : "Edit"}
        </button>
      </div>
      {open && (
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await run(
              () =>
                patch(`/planning/task-templates/${t.key}`, {
                  version: t.version,
                  title: f.title.trim(),
                  minutes_fixed: Number(f.minutes_fixed) || 0,
                  minutes_per_unit: Number(f.minutes_per_unit) || 0,
                  requires_downtime: f.requires_downtime,
                  active: f.active,
                  steps: f.steps
                    .split("\n")
                    .map((s) => s.trim())
                    .filter(Boolean),
                  evidence: evidence.filter((x) => x.label.trim()),
                }),
              "Task template saved",
            );
            if (r !== undefined) {
              setOpen(false);
              onSaved();
            }
          }}
        >
          <div className="form-grid">
            <Field id={`tk-${t.key}-title`} label="Title">
              <input id={`tk-${t.key}-title`} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
            </Field>
            <Field id={`tk-${t.key}-min`} label="Minutes for the task">
              <input id={`tk-${t.key}-min`} inputMode="numeric" value={f.minutes_fixed} onChange={(e) => setF({ ...f, minutes_fixed: e.target.value })} />
            </Field>
            <Field id={`tk-${t.key}-unit`} label="Minutes for each device">
              <input id={`tk-${t.key}-unit`} inputMode="numeric" value={f.minutes_per_unit} onChange={(e) => setF({ ...f, minutes_per_unit: e.target.value })} />
            </Field>
          </div>
          <div className="row">
            <Check checked={f.requires_downtime} onChange={(v) => setF({ ...f, requires_downtime: v })}>
              Needs downtime
            </Check>
            <Check checked={f.active} onChange={(v) => setF({ ...f, active: v })}>
              Used in new plans
            </Check>
          </div>
          <Field id={`tk-${t.key}-steps`} label="Steps, in order" hint="One step per row. Engineers tick them one by one.">
            <textarea id={`tk-${t.key}-steps`} rows={6} value={f.steps} onChange={(e) => setF({ ...f, steps: e.target.value })} />
          </Field>
          <div className="stack">
            <strong className="small">Evidence</strong>
            {evidence.map((x, i) => (
              <div key={i} className="row">
                <select aria-label="Type" value={x.type} onChange={(e) => setEvidence(evidence.map((y, j) => (j === i ? { ...y, type: e.target.value } : y)))}>
                  {EVIDENCE_TYPES.map((ty) => (
                    <option key={ty} value={ty}>
                      {ty.replace("_", " ")}
                    </option>
                  ))}
                </select>
                <input
                  aria-label="What to show"
                  value={x.label}
                  onChange={(e) => setEvidence(evidence.map((y, j) => (j === i ? { ...y, label: e.target.value } : y)))}
                  style={{ flex: 1, minWidth: 180 }}
                />
                <Check checked={x.required} onChange={(v) => setEvidence(evidence.map((y, j) => (j === i ? { ...y, required: v } : y)))}>
                  Needed
                </Check>
                <button type="button" className="btn quiet small" onClick={() => setEvidence(evidence.filter((_, j) => j !== i))}>
                  Remove
                </button>
              </div>
            ))}
            <div>
              <button type="button" className="btn small" onClick={() => setEvidence([...evidence, { type: "photo", label: "", required: true }])}>
                Add evidence
              </button>
            </div>
          </div>
          <div>
            <button className="btn primary" disabled={busy || f.title.trim().length < 3}>
              Save task template
            </button>
          </div>
          <p className="muted small">Plans already locked keep the steps they were made with.</p>
        </form>
      )}
    </div>
  );
}

function TaskTemplates() {
  const list = useData<S["TaskTemplateOut"][]>("/planning/task-templates");
  if (list.error) return <Notice tone="bad">{list.error}</Notice>;
  if (!list.data) return <Skeleton lines={6} />;
  return (
    <div className="stack">
      <p className="muted">The steps and evidence of each kind of field task. The arrival photo and the prechecks are added to every task.</p>
      {list.data.map((t) => (
        <TaskTemplate key={`${t.key}-${t.version}`} t={t} onSaved={() => void list.reload()} />
      ))}
    </div>
  );
}

export default function Templates() {
  const { can } = useMe();
  const [tab, setTab] = useState<"boq" | "tasks">("boq");
  if (!can("template:edit")) return <Notice tone="warn">Only template editors change these.</Notice>;
  return (
    <div>
      <Back href="/settings" label="Settings" />
      <div className="page-head">
        <div>
          <h1>Templates</h1>
          <p>Change what a finding turns into and how a field task is done. Every save is a new revision.</p>
        </div>
      </div>
      <Tabs
        label="Templates"
        tabs={[
          { id: "boq", label: "BOQ lines" },
          { id: "tasks", label: "Field tasks" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "boq" ? <BoqTemplates /> : <TaskTemplates />}
    </div>
  );
}
