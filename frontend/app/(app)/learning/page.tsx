"use client";
import { dateTime, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton, useAction } from "@/components/ui";

type Report = {
  examples: number;
  labelled: number;
  usable_groups: number;
  needed_groups: number;
  rules_top1: number | null;
  shadow: null | {
    model_id: string;
    number: number;
    weights: Record<string, number>;
    runs: number;
    agreement: number | null;
    model_top1: number | null;
    disagreements: { category: string; rules: string; model: string; at: string }[];
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

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "not enough data" : `${Math.round(v * 100)}%`);

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

export default function Learning() {
  const { can } = useMe();
  const readable = can("ml:read");
  const manage = can("ml:manage");
  const rep = useData<Report>(readable ? "/ml/report" : null);
  const sets = useData<S["TrainingSetOut"][]>(readable ? "/ml/training-sets" : null);
  const models = useData<S["ModelOut"][]>(readable ? "/ml/models" : null);
  const { busy, run } = useAction();
  const reload = () => {
    rep.reload();
    sets.reload();
    models.reload();
  };

  if (!readable) return <Notice tone="warn">Your role does not see the learning page.</Notice>;
  const r = rep.data;
  const ready = !!r && r.usable_groups >= r.needed_groups;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Learning</h1>
          <p>
            The recommender learns from the BOQs customers accept: which of the suggested products they actually took. A learned ranker only runs in
            shadow mode. It never changes a BOQ; it is compared with the rules here until someone decides it has earned more.
          </p>
        </div>
      </div>

      {rep.error && <Notice tone="bad">{rep.error}</Notice>}
      {!r && !rep.error && <Skeleton lines={5} />}

      {r && (
        <div className="section">
          <h2>What there is to learn from</h2>
          <div className="learn-progress">
            <progress max={r.needed_groups} value={Math.min(r.usable_groups, r.needed_groups)} aria-label="Accepted recommendations collected" />
            <p>
              <strong>
                {r.usable_groups} of {r.needed_groups}
              </strong>{" "}
              accepted recommendations needed before a model can be trained.
              {!ready && " Each BOQ a customer accepts, where the recommender offered more than one product, adds to this."}
            </p>
          </div>
          <dl className="kv">
            <dt>Candidates recorded</dt>
            <dd>{r.examples}</dd>
            <dt>With the customer&apos;s decision</dt>
            <dd>{r.labelled}</dd>
            <dt>Rules picked what the customer took</dt>
            <dd>{pct(r.rules_top1)}</dd>
          </dl>
        </div>
      )}

      {r?.shadow && (
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
          <h3>Where they disagree</h3>
          {r.shadow.disagreements.length === 0 ? (
            <p className="muted">No disagreements yet.</p>
          ) : (
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

      <div className="section">
        <div className="row between">
          <h2>Training sets</h2>
          {manage && (
            <button
              className="btn"
              disabled={busy || !r?.labelled}
              onClick={async () => {
                if (await run(() => post("/ml/training-sets"), "Training set frozen")) reload();
              }}
            >
              Freeze a new training set
            </button>
          )}
        </div>
        <p className="muted">A frozen copy of every decision so far. Models train on one of these, never on live data, so each model can be traced to exactly what it learned from.</p>
        {!sets.data?.length ? (
          <Empty title="No training sets yet">{r?.labelled ? "Freeze one when you are ready to train." : "One can be frozen once a customer has accepted a recommended BOQ."}</Empty>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Set</th>
                <th>Decisions</th>
                <th>Usable</th>
                <th className="right">Frozen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sets.data.map((s) => {
                const usable = Number(s.data_card.usable_groups ?? 0);
                return (
                  <tr key={s.id}>
                    <td data-label="Set">Set {s.number}</td>
                    <td data-label="Decisions">
                      {String(s.data_card.rows)} candidates from {String(s.data_card.boqs)} BOQs
                    </td>
                    <td data-label="Usable">
                      {usable} of {r?.needed_groups ?? 20} needed
                    </td>
                    <td data-label="Frozen" className="right">
                      {dateTime(s.frozen_at)}
                    </td>
                    <td className="right">
                      {manage && (
                        <button
                          className="btn quiet small"
                          disabled={busy || usable < (r?.needed_groups ?? 20)}
                          title={usable < (r?.needed_groups ?? 20) ? "Too few decisions in this set to train on" : undefined}
                          onClick={async () => {
                            if (await run(() => post("/ml/models", { training_set_id: s.id }), "Model trained")) reload();
                          }}
                        >
                          Train
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="section">
        <h2>Models</h2>
        {!models.data?.length ? (
          <Empty title="No models yet">A model can be trained once a training set holds enough decisions.</Empty>
        ) : (
          models.data.map((m) => (
            <div key={m.id} className="model-card">
              <div className="row between">
                <h3>
                  Model {m.number}{" "}
                  <Badge tone={m.status === "shadow" ? "accent" : m.status === "retired" ? undefined : "ok"}>
                    {m.status === "shadow" ? "Shadow" : m.status === "retired" ? "Retired" : "Trained"}
                  </Badge>
                </h3>
                {manage && m.status !== "retired" && (
                  <div className="row">
                    {m.status !== "shadow" && (
                      <button
                        className="btn small"
                        disabled={busy}
                        onClick={async () => {
                          if (await run(() => post(`/ml/models/${m.id}/status`, { status: "shadow" }), "Shadow mode started")) reload();
                        }}
                      >
                        Run in shadow mode
                      </button>
                    )}
                    <button
                      className="btn quiet small"
                      disabled={busy}
                      onClick={async () => {
                        if (await run(() => post(`/ml/models/${m.id}/status`, { status: "retired" }), "Model retired")) reload();
                      }}
                    >
                      Retire
                    </button>
                  </div>
                )}
              </div>
              <p className="muted small">
                Trained {dateTime(m.created_at)} on set {String(m.metrics.training_set)}. On {String(m.metrics.test_groups)}{" "}
                {m.metrics.holdout ? "decisions it had not seen" : "decisions (too few to hold any back)"}, it picked what the customer took{" "}
                {pct(m.metrics.model_top1 as number | null)} of the time; the rules {pct(m.metrics.rules_top1 as number | null)}.
              </p>
              <Weights weights={m.weights} />
            </div>
          ))
        )}
      </div>
    </>
  );
}
