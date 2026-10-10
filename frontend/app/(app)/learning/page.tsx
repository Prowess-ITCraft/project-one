"use client";
import { useState } from "react";
import { dateTime, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, useAction } from "@/components/ui";
import { Drawer, Tabs } from "@/components/kit";

type Kind = "ranker" | "boq_lines" | "price_drift";
type F1 = { precision: number | null; recall: number | null; f1: number | null } | null;
type Report = {
  enabled: boolean;
  examples: number;
  labelled: number;
  usable_groups: number;
  needed_groups: number;
  rules_top1: number | null;
  shadow_rule: { days: number; comparisons: number };
  shadow: null | {
    model_id: string;
    number: number;
    weights: Record<string, number>;
    runs: number;
    agreement: number | null;
    model_top1: number | null;
    disagreements: { category: string; rules: string; model: string; at: string }[];
  };
  lines: {
    drafted: number;
    accepted: number;
    needed: number;
    rules: F1;
    approved_model: number | null;
    shadow: null | { model_id: string; number: number; since: string | null; compared: number; model: F1; rules_same_boqs: F1 };
  };
  prices: {
    points: number;
    needed: number;
    flagged_90_days: number;
    alerted_90_days: number;
    latest_flags: { item: string; reason: string | null; quoted_on: string; item_id: string }[];
    shadow: null | { model_id: string; number: number; compared: number; both_flag: number; only_model: number; only_rule: number };
  };
};

// The rule engine's weights (backend boq/recommend.py DEFAULT_WEIGHTS), shown for comparison.
const RULES: Record<string, number> = {
  need_fit: 0.25,
  budget_fit: 0.2,
  tco: 0.15,
  market: 0.1,
  lifecycle: 0.1,
  vendor: 0.1,
  stock: 0.05,
  history: 0.05,
};
const LABEL: Record<string, string> = {
  need_fit: "Fits the need",
  budget_fit: "Within budget",
  tco: "Three-year cost",
  market: "Market standing",
  lifecycle: "Support life left",
  vendor: "Customer's preferred vendor",
  stock: "In stock",
  history: "Used in past BOQs",
};
const KIND_TITLE: Record<Kind, string> = { ranker: "Product ranker", boq_lines: "BOQ lines", price_drift: "Prices" };

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "not enough data" : `${Math.round(v * 100)}%`);
const f1 = (v: F1) => (v ? `${pct(v.f1)} (precision ${pct(v.precision)}, recall ${pct(v.recall)})` : "not enough data");

function Weights({ weights }: { weights: Record<string, number> }) {
  return (
    <table className="table weights">
      <thead>
        <tr>
          <th>Criterion</th>
          <th>Rules</th>
          <th>Learned</th>
        </tr>
      </thead>
      <tbody>
        {Object.keys(RULES).map((k) => (
          <tr key={k}>
            <td data-label="Criterion">{LABEL[k]}</td>
            <td data-label="Rules">
              <span className="wbar" style={{ "--w": RULES[k] } as React.CSSProperties} />
              {pct(RULES[k])}
            </td>
            <td data-label="Learned">
              <span className="wbar learned" style={{ "--w": weights[k] ?? 0 } as React.CSSProperties} />
              {pct(weights[k] ?? 0)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Progress({ have, need, what }: { have: number; need: number; what: string }) {
  return (
    <div className="learn-progress">
      <progress max={need} value={Math.min(have, need)} aria-label={what} />
      <p>
        <strong>
          {have} of {need}
        </strong>{" "}
        {what}
      </p>
    </div>
  );
}

function RankerReport({ r }: { r: Report }) {
  return (
    <>
      <div className="section">
        <h2>What there is to learn from</h2>
        <p className="muted">Which of the products the recommender suggested the customer actually took.</p>
        <Progress have={r.usable_groups} need={r.needed_groups} what="accepted recommendations needed before a model can be trained." />
        <dl className="kv">
          <dt>Candidates recorded</dt>
          <dd>{r.examples}</dd>
          <dt>With the customer&apos;s decision</dt>
          <dd>{r.labelled}</dd>
          <dt>Rules picked what the customer took</dt>
          <dd>{pct(r.rules_top1)}</dd>
        </dl>
      </div>
      {r.shadow && (
        <div className="section">
          <h2>
            Model {r.shadow.number} in shadow mode <Badge tone="accent">Shadow</Badge>
          </h2>
          <dl className="kv">
            <dt>Recommendations seen</dt>
            <dd>{r.shadow.runs}</dd>
            <dt>Agrees with the rules</dt>
            <dd>{pct(r.shadow.agreement)}</dd>
            <dt>Picked what the customer took</dt>
            <dd>
              {pct(r.shadow.model_top1)} <span className="muted">(rules: {pct(r.rules_top1)})</span>
            </dd>
          </dl>
          {r.shadow.disagreements.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Product type</th>
                  <th>Rules picked</th>
                  <th>Model would pick</th>
                  <th className="right">When</th>
                </tr>
              </thead>
              <tbody>
                {r.shadow.disagreements.map((d, i) => (
                  <tr key={i}>
                    <td data-label="Product type">{d.category}</td>
                    <td data-label="Rules picked">{d.rules}</td>
                    <td data-label="Model would pick">{d.model}</td>
                    <td data-label="When" className="right">
                      {dateTime(d.at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}

function LinesReport({ r }: { r: Report }) {
  const l = r.lines;
  return (
    <>
      <div className="section">
        <h2>What there is to learn from</h2>
        <p className="muted">
          Each accepted BOQ teaches which lines a set of audit findings leads to. The rules (the BOQ templates) draft lines; this model
          learns from what customers actually bought.
        </p>
        <Progress have={l.accepted} need={l.needed} what="accepted BOQs drafted from an audit, needed before a model can be trained." />
        <dl className="kv">
          <dt>BOQs drafted</dt>
          <dd>{l.drafted}</dd>
          <dt>Accepted by the customer</dt>
          <dd>{l.accepted}</dd>
          <dt>Rules drafted what was bought</dt>
          <dd>{f1(l.rules)}</dd>
          <dt>Approved model</dt>
          <dd>{l.approved_model ? `Model ${l.approved_model}, suggesting lines in the BOQ editor` : "None"}</dd>
        </dl>
      </div>
      {l.shadow && (
        <div className="section">
          <h2>
            Model {l.shadow.number} in shadow mode <Badge tone="accent">Shadow</Badge>
          </h2>
          <dl className="kv">
            <dt>In shadow mode since</dt>
            <dd>{l.shadow.since ? dateTime(l.shadow.since) : "unknown"}</dd>
            <dt>Accepted BOQs compared</dt>
            <dd>
              {l.shadow.compared} of {r.shadow_rule.comparisons} needed for approval
            </dd>
            <dt>Model predicted what was bought</dt>
            <dd>{f1(l.shadow.model)}</dd>
            <dt>Rules, on the same BOQs</dt>
            <dd>{f1(l.shadow.rules_same_boqs)}</dd>
          </dl>
        </div>
      )}
    </>
  );
}

function PricesReport({ r }: { r: Report }) {
  const p = r.prices;
  return (
    <>
      <div className="section">
        <h2>Price checks</h2>
        <p className="muted">
          Every price entered in the price book is compared with the item&apos;s earlier prices. One far from its history is sent to the
          sales heads as advice. That rule always runs; a model can learn the whole price book and run next to it.
        </p>
        <dl className="kv">
          <dt>Prices recorded</dt>
          <dd>{p.points}</dd>
          <dt>Flagged in the last 90 days</dt>
          <dd>{p.flagged_90_days}</dd>
          <dt>Sales heads told</dt>
          <dd>{p.alerted_90_days}</dd>
        </dl>
        <Progress have={p.points} need={p.needed} what="prices needed before a price model can be trained." />
        {p.latest_flags.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Why</th>
                <th className="right">Quoted</th>
              </tr>
            </thead>
            <tbody>
              {p.latest_flags.map((f, i) => (
                <tr key={i}>
                  <td data-label="Item">
                    <a href={`/catalogue/${f.item_id}`}>{f.item}</a>
                  </td>
                  <td data-label="Why">{f.reason}</td>
                  <td data-label="Quoted" className="right">
                    {f.quoted_on}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {p.shadow && (
        <div className="section">
          <h2>
            Model {p.shadow.number} in shadow mode <Badge tone="accent">Shadow</Badge>
          </h2>
          <dl className="kv">
            <dt>Prices compared</dt>
            <dd>{p.shadow.compared}</dd>
            <dt>Both flagged</dt>
            <dd>{p.shadow.both_flag}</dd>
            <dt>Only the model flagged</dt>
            <dd>{p.shadow.only_model}</dd>
            <dt>Only the rule flagged</dt>
            <dd>{p.shadow.only_rule}</dd>
          </dl>
        </div>
      )}
    </>
  );
}

function CardDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const c = useData<S["CardOut"]>(`/ml/models/${id}/card`);
  return (
    <Drawer title="Model card" onClose={onClose}>
      {!c.data ? <Skeleton lines={8} /> : <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{c.data.markdown}</pre>}
    </Drawer>
  );
}

function Approve({ m, onDone }: { m: S["ModelOut"]; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const { busy, run } = useAction();
  if (!open)
    return (
      <button className="btn small primary" onClick={() => setOpen(true)}>
        Approve
      </button>
    );
  return (
    <div className="stack" style={{ width: "100%" }}>
      <Field id={`ap-${m.id}`} label="Why it is good enough to advise people" hint="Kept on the model card and in the audit log.">
        <textarea id={`ap-${m.id}`} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="row">
        <button
          className="btn primary small"
          disabled={busy || note.trim().length < 10}
          onClick={async () => {
            if (await run(() => post(`/ml/models/${m.id}/approve`, { note: note.trim() }), "Model approved")) onDone();
          }}
        >
          Approve the model
        </button>
        <button className="btn quiet small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function SetsAndModels({ kind, report, reload }: { kind: Kind; report: Report; reload: () => void }) {
  const { can } = useMe();
  const manage = can("ml:manage");
  const sets = useData<S["TrainingSetOut"][]>("/ml/training-sets");
  const models = useData<S["ModelOut"][]>("/ml/models");
  const [card, setCard] = useState<string | null>(null);
  const { busy, run } = useAction();
  const mine = (sets.data ?? []).filter((s) => s.kind === kind);
  const mineModels = (models.data ?? []).filter((m) => m.kind === kind);
  const refresh = () => {
    reload();
    void sets.reload();
    void models.reload();
  };
  const have = kind === "ranker" ? report.labelled : kind === "boq_lines" ? report.lines.accepted : report.prices.points;
  return (
    <>
      <div className="section">
        <div className="row between">
          <h2>Training sets</h2>
          {manage && (
            <button
              className="btn"
              disabled={busy || !have || !report.enabled}
              onClick={async () => {
                if (await run(() => post("/ml/training-sets", { kind }), "Training set frozen")) refresh();
              }}
            >
              Freeze a new training set
            </button>
          )}
        </div>
        <p className="muted">
          A frozen copy of the examples so far. Models train on one of these, never on live data, so each model can be traced to exactly what
          it learned from.
        </p>
        {mine.length === 0 ? (
          <Empty title="No training sets yet">{have ? "Freeze one when you are ready to train." : "Examples are recorded as work happens."}</Empty>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Set</th>
                <th>Examples</th>
                <th className="right">Frozen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {mine.map((s) => (
                <tr key={s.id}>
                  <td data-label="Set">Set {s.number}</td>
                  <td data-label="Examples">{String(s.data_card.rows)}</td>
                  <td data-label="Frozen" className="right">
                    {dateTime(s.frozen_at)}
                  </td>
                  <td className="right">
                    {manage && (
                      <button
                        className="btn quiet small"
                        disabled={busy || !report.enabled}
                        onClick={async () => {
                          if (await run(() => post("/ml/models", { training_set_id: s.id }), "Model trained")) refresh();
                        }}
                      >
                        Train
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
        <h2>Models</h2>
        <p className="muted">
          A model runs in shadow mode first: its answers are recorded next to the rules&apos;. Only the Director approves one, after{" "}
          {report.shadow_rule.days} days and {report.shadow_rule.comparisons} comparisons. Even approved, a model only advises; it never
          changes a BOQ, a price, a verdict or a certificate.
        </p>
        {mineModels.length === 0 ? (
          <Empty title="No models yet">A model can be trained once a training set holds enough examples.</Empty>
        ) : (
          mineModels.map((m) => (
            <div key={m.id} className="model-card">
              <div className="row between">
                <h3>
                  Model {m.number}{" "}
                  <Badge tone={m.status === "shadow" ? "accent" : m.status === "approved" ? "ok" : undefined}>
                    {m.status === "shadow" ? "Shadow" : m.status === "approved" ? "Approved" : m.status === "retired" ? "Retired" : "Trained"}
                  </Badge>
                </h3>
                <div className="row">
                  <button className="btn quiet small" onClick={() => setCard(m.id)}>
                    Model card
                  </button>
                  {manage && m.status === "trained" && (
                    <button
                      className="btn small"
                      disabled={busy}
                      onClick={async () => {
                        if (await run(() => post(`/ml/models/${m.id}/status`, { status: "shadow" }), "Shadow mode started")) refresh();
                      }}
                    >
                      Run in shadow mode
                    </button>
                  )}
                  {can("ml:approve") && m.status === "shadow" && <Approve m={m} onDone={refresh} />}
                  {manage && m.status !== "retired" && (
                    <button
                      className="btn quiet small"
                      disabled={busy}
                      onClick={async () => {
                        if (await run(() => post(`/ml/models/${m.id}/status`, { status: "retired" }), "Model retired")) refresh();
                      }}
                    >
                      Retire
                    </button>
                  )}
                </div>
              </div>
              <p className="muted small">
                Trained {dateTime(m.created_at)} on set {String(m.metrics.training_set)}
                {m.shadow_started_at ? `, in shadow mode since ${dateTime(m.shadow_started_at)}` : ""}
                {m.approved_at ? `, approved ${dateTime(m.approved_at)}` : ""}.
              </p>
              {kind === "ranker" && (
                <>
                  <p className="muted small">
                    It picked what the customer took {pct(m.metrics.model_top1 as number | null)} of the time; the rules{" "}
                    {pct(m.metrics.rules_top1 as number | null)}.
                  </p>
                  <Weights weights={m.weights} />
                </>
              )}
              {kind === "boq_lines" && (
                <p className="small">
                  {String(m.metrics.algo === "lightgbm" ? "LightGBM" : "Logistic regression")}, {String(m.metrics.labels)} lines learned. Predicted
                  what was bought {f1(m.metrics.model as F1)}; the templates {f1(m.metrics.rules as F1)}.
                </p>
              )}
              {kind === "price_drift" && (
                <p className="small">
                  LightGBM on {String(m.metrics.points)} prices of {String(m.metrics.items)} items. Typical error {String(m.metrics.mean_abs_error_pct)}{" "}
                  percent.
                </p>
              )}
              {m.approval_note && <p className="small">Approved because: {m.approval_note}</p>}
            </div>
          ))
        )}
      </div>
      {card && <CardDrawer id={card} onClose={() => setCard(null)} />}
    </>
  );
}

export default function Learning() {
  const { can } = useMe();
  const readable = can("ml:read");
  const rep = useData<Report>(readable ? "/ml/report" : null);
  const [kind, setKind] = useState<Kind>("ranker");
  if (!readable) return <Notice tone="warn">Your role does not see the learning page.</Notice>;
  const r = rep.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Learning</h1>
          <p>
            Classical models that learn from what customers accepted and from the price book. They run in shadow mode next to the rules and are
            compared here; nothing they say changes a BOQ, a verdict or a certificate.
          </p>
        </div>
      </div>
      {rep.error && <Notice tone="bad">{rep.error}</Notice>}
      {!r && !rep.error && <Skeleton lines={5} />}
      {r && !r.enabled && <Notice tone="warn">Learning is switched off. No examples are recorded and no model runs. An Admin can switch it on in Settings.</Notice>}
      {r && (
        <>
          <Tabs
            label="Kind of model"
            tabs={(Object.keys(KIND_TITLE) as Kind[]).map((k) => ({ id: k, label: KIND_TITLE[k] }))}
            value={kind}
            onChange={setKind}
          />
          {kind === "ranker" && <RankerReport r={r} />}
          {kind === "boq_lines" && <LinesReport r={r} />}
          {kind === "price_drift" && <PricesReport r={r} />}
          <SetsAndModels kind={kind} report={r} reload={() => void rep.reload()} />
        </>
      )}
    </>
  );
}
