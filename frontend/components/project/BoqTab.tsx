"use client";
import { useEffect, useMemo, useState } from "react";
import { date, dateTime, get, money, openDoc as openApiDoc, post, type S } from "@/lib/api";
import { useData, useMe, useToast } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, useAction } from "@/components/ui";
import { Check, ConfirmButton, Drawer, toList } from "@/components/kit";
import { EstimatePanel } from "@/components/project/EstimatePanel";

type Boq = S["BoqOut"];
type Line = S["LineOut"];
type Op = Record<string, unknown>;
type LineEdit = Partial<{ qty: string; unit_price: string; reason: string }>;

const FLAG: Record<string, [string, "ok" | "warn" | "bad" | "accent" | undefined]> = {
  no_price: ["No price", "bad"],
  price_expired: ["Price expired", "bad"],
  zero_qty: ["Quantity 0", "bad"],
  price_expiring: ["Price expires soon", "warn"],
  manual_price: ["Price by hand", "accent"],
  below_cost: ["Below cost", "bad"],
  low_margin: ["Margin under the minimum", "warn"],
  out_of_stock: ["Out of stock", "warn"],
  on_order: ["On order", "warn"],
  end_of_life: ["End of life", "warn"],
  needs_manual: ["Choose a product", "warn"],
};
const STAGE_LABEL: Record<string, string> = {
  drafting: "Drafting",
  pricing_review: "Waiting for pricing approval",
  pricing_approved: "Pricing approved",
};

function rangeText(a: string, b: string) {
  return a === b ? money(a) : `${money(a)} to ${money(b)}`;
}

function LineDrawer({
  line,
  boq,
  onClose,
  queue,
}: {
  line: Line;
  boq: Boq;
  onClose: () => void;
  queue: (ops: Op[]) => void;
}) {
  const [f, setF] = useState({
    title: line.title,
    description: line.description ?? "",
    inclusions: (line.inclusions ?? []).join("\n"),
    qty: String(line.qty),
    uom: line.uom,
    gst_rate: line.gst_rate,
    cost: line.cost ?? "",
    unit_price: line.unit_price ?? "",
    reason: line.manual_price_reason ?? "",
    notes: line.notes ?? "",
    option_group: line.option_group ?? "",
  });
  const [hist, setHist] = useState<Record<string, string | number | null> | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const priceChanged = f.unit_price !== (line.unit_price ?? "");
  const fields: Record<string, unknown> = {
    title: f.title,
    description: f.description,
    inclusions: toList(f.inclusions.replace(/,/g, ";")).length ? f.inclusions.split("\n").map((x) => x.trim()).filter(Boolean) : [],
    qty: Number(f.qty),
    uom: f.uom,
    gst_rate: f.gst_rate,
    notes: f.notes || null,
    option_group: f.option_group || null,
  };
  if (f.cost !== (line.cost ?? "")) fields.cost = f.cost || null;
  if (priceChanged) {
    fields.unit_price = f.unit_price || null;
    if (f.unit_price) fields.manual_price_reason = f.reason;
  }
  const needsReason = priceChanged && !!f.unit_price;

  async function loadHistory() {
    try {
      setHist(await get(`/boq/${boq.id}/lines/${line.id}/history`));
    } catch {
      setHist({ note: "No history is available." });
    }
  }

  return (
    <Drawer title={`Line ${line.ref}`} onClose={onClose}>
      <Field id="lt" label="Component">
        <input id="lt" type="text" value={f.title} onChange={set("title")} />
      </Field>
      <Field id="ld" label="Description">
        <textarea id="ld" value={f.description} onChange={set("description")} />
      </Field>
      <Field id="li" label="Inclusions" hint="One per line. They print as bullets under the component.">
        <textarea id="li" style={{ minHeight: 120 }} value={f.inclusions} onChange={set("inclusions")} />
      </Field>
      <div className="grid3">
        <Field id="lq" label="Quantity">
          <input id="lq" type="number" min={0} value={f.qty} onChange={set("qty")} />
        </Field>
        <Field id="lu" label="Unit">
          <input id="lu" type="text" value={f.uom} onChange={set("uom")} />
        </Field>
        <Field id="lg" label="GST %">
          <input id="lg" type="text" inputMode="decimal" value={f.gst_rate} onChange={set("gst_rate")} />
        </Field>
      </div>
      <div className="grid2">
        <Field id="lp" label="Unit price (INR)" hint={line.price_source === "price_book" ? "From the price book. Changing it makes it a hand price." : undefined}>
          <input id="lp" type="text" inputMode="decimal" value={f.unit_price} onChange={set("unit_price")} />
        </Field>
        <Field id="lc" label="Cost price (INR)" hint="Private. Used for the margin check.">
          <input id="lc" type="text" inputMode="decimal" value={f.cost} onChange={set("cost")} />
        </Field>
      </div>
      {line.hint_price && (
        <p className="stepnote">
          {line.hint_note} Last price {money(line.hint_price)}.{" "}
          <button className="btn quiet small" onClick={() => setF({ ...f, unit_price: line.hint_price ?? "" })}>
            Use it
          </button>
        </p>
      )}
      {needsReason && (
        <Field id="lr" label="Where did this price come from?" hint="For example: distributor quote by phone, 30 Sep. Required for a hand price.">
          <input id="lr" type="text" value={f.reason} onChange={set("reason")} />
        </Field>
      )}
      <Field id="lo" label="Alternative group" hint="Lines in the same group are alternatives: 5A, 5B. Leave empty for a normal line.">
        <input id="lo" type="text" value={f.option_group} onChange={set("option_group")} />
      </Field>
      <Field id="ln" label="Internal note">
        <textarea id="ln" value={f.notes} onChange={set("notes")} />
      </Field>
      <div className="row">
        <button
          className="btn primary"
          disabled={(needsReason && f.reason.trim().length < 3) || !f.title.trim()}
          onClick={() => {
            queue([{ op: "update_line", id: line.id, fields }]);
            onClose();
          }}
        >
          Add to changes
        </button>
        <button className="btn" onClick={loadHistory}>
          What past BOQs say
        </button>
      </div>
      {hist && (
        <Notice>
          {hist.occurrences ? (
            <>
              Seen in {hist.occurrences} past BOQ{hist.occurrences === 1 ? "" : "s"} for {hist.customers} customer
              {hist.customers === 1 ? "" : "s"}. Typical quantity {hist.typical_qty}, median price {money(hist.median_unit_price as string)}
              {hist.last_seen ? `, last on ${date(hist.last_seen as string)}` : ""}. {hist.note}
            </>
          ) : (
            <>Nothing similar in the library yet. {hist.note}</>
          )}
        </Notice>
      )}
      {line.source.note ? <p className="stepnote">Why it is here: {String(line.source.note)}</p> : null}
    </Drawer>
  );
}

function CatalogueDrawer({
  boq,
  sectionId,
  optionGroup,
  pending,
  onClose,
  onAdded,
}: {
  boq: Boq;
  sectionId: string;
  optionGroup: string | null;
  pending: boolean;
  onClose: () => void;
  onAdded: (b: Boq) => void;
}) {
  const [q, setQ] = useState("");
  const items = useData<{ items: S["ItemOut"][] }>(`/catalogue/items?size=20${q ? `&q=${encodeURIComponent(q)}` : ""}`);
  const { busy, run } = useAction();
  const [reason, setReason] = useState("Added from the catalogue");
  return (
    <Drawer title="Add from the catalogue" onClose={onClose}>
      {pending && <Notice tone="warn">Save or discard your pending changes first, so nothing is lost.</Notice>}
      <input type="search" aria-label="Search the catalogue" placeholder="Search by name or code" value={q} onChange={(e) => setQ(e.target.value)} />
      <Field id="cr" label="Reason">
        <input id="cr" type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {items.loading && !items.data && <Skeleton lines={4} />}
      <table className="table">
        <tbody>
          {(items.data?.items ?? []).map((i) => (
            <tr key={i.id}>
              <td>
                <div className="title">{i.name}</div>
                <div className="muted small mono">{i.code}</div>
              </td>
              <td className="right">
                <button
                  className="btn small"
                  disabled={busy || pending || reason.trim().length < 3}
                  onClick={async () => {
                    const r = await run(
                      () => post<Boq>(`/boq/${boq.id}/add-item`, { draft_rev: boq.draft_rev, reason, item_code: i.code, section_id: sectionId, qty: 1, option_group: optionGroup }),
                      "Added",
                    );
                    if (r) onAdded(r);
                  }}
                >
                  Add
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Drawer>
  );
}

function BlankLineDrawer({ sectionId, onClose, queue }: { sectionId: string; onClose: () => void; queue: (ops: Op[]) => void }) {
  const [f, setF] = useState({ title: "", description: "", qty: "1", uom: "nos", unit_price: "", reason: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Drawer title="Add a line by hand" onClose={onClose}>
      <Field id="bt" label="Component">
        <input id="bt" type="text" value={f.title} onChange={set("title")} />
      </Field>
      <Field id="bd" label="Description">
        <textarea id="bd" value={f.description} onChange={set("description")} />
      </Field>
      <div className="grid3">
        <Field id="bq" label="Quantity">
          <input id="bq" type="number" min={0} value={f.qty} onChange={set("qty")} />
        </Field>
        <Field id="bu" label="Unit">
          <input id="bu" type="text" value={f.uom} onChange={set("uom")} />
        </Field>
        <Field id="bp" label="Unit price (INR)">
          <input id="bp" type="text" inputMode="decimal" value={f.unit_price} onChange={set("unit_price")} />
        </Field>
      </div>
      {f.unit_price && (
        <Field id="br" label="Where did this price come from?">
          <input id="br" type="text" value={f.reason} onChange={set("reason")} />
        </Field>
      )}
      <button
        className="btn primary"
        disabled={!f.title.trim() || (!!f.unit_price && f.reason.trim().length < 3)}
        onClick={() => {
          const line: Record<string, unknown> = { title: f.title, description: f.description, qty: Number(f.qty), uom: f.uom };
          if (f.unit_price) Object.assign(line, { unit_price: f.unit_price, manual_price_reason: f.reason });
          queue([{ op: "add_line", section_id: sectionId, line }]);
          onClose();
        }}
      >
        Add to changes
      </button>
    </Drawer>
  );
}

function SettingsPanel({ boq, queue, locked }: { boq: Boq; queue: (ops: Op[]) => void; locked: boolean }) {
  const s = boq.settings as Record<string, unknown>;
  const [terms, setTerms] = useState(boq.terms.join("\n"));
  return (
    <div className="section">
      <h2>Quotation settings</h2>
      <p className="stepnote">Totals and GST rows are off by default, like the ITCraft sample. Turn them on per quote.</p>
      <div className="row" style={{ margin: "10px 0" }}>
        <Check checked={!!s.show_totals} onChange={(v) => !locked && queue([{ op: "update_settings", fields: { show_totals: v } }])}>
          Show sub total and grand total
        </Check>
        <Check checked={!!s.show_gst_rows} onChange={(v) => !locked && queue([{ op: "update_settings", fields: { show_gst_rows: v } }])}>
          Show GST row
        </Check>
      </div>
      <div className="grid3">
        <Field id="sv" label="Valid for (days)">
          <input id="sv" type="number" min={1} defaultValue={String(s.validity_days ?? 5)} disabled={locked}
            onBlur={(e) => e.target.value !== String(s.validity_days) && queue([{ op: "update_settings", fields: { validity_days: Number(e.target.value) } }])} />
        </Field>
        <Field id="sn" label="Signed by">
          <input id="sn" type="text" defaultValue={String(s.signatory_name ?? "")} disabled={locked}
            onBlur={(e) => e.target.value !== s.signatory_name && queue([{ op: "update_settings", fields: { signatory_name: e.target.value } }])} />
        </Field>
        <Field id="sd" label="Designation">
          <input id="sd" type="text" defaultValue={String(s.signatory_designation ?? "")} disabled={locked}
            onBlur={(e) => e.target.value !== s.signatory_designation && queue([{ op: "update_settings", fields: { signatory_designation: e.target.value } }])} />
        </Field>
      </div>
      <Field id="si" label="Opening sentence">
        <input id="si" type="text" defaultValue={String(s.intro ?? "")} disabled={locked}
          onBlur={(e) => e.target.value !== s.intro && queue([{ op: "update_settings", fields: { intro: e.target.value } }])} />
      </Field>
      <Field id="stm" label="Terms and conditions" hint="One per line.">
        <textarea id="stm" style={{ minHeight: 150 }} value={terms} disabled={locked} onChange={(e) => setTerms(e.target.value)}
          onBlur={() => terms.trim() !== boq.terms.join("\n").trim() && queue([{ op: "set_terms", terms: terms.split("\n").map((t) => t.trim()).filter(Boolean) }])} />
      </Field>
    </div>
  );
}

export function BoqTab({ projectId, stage, autoEstimate }: { projectId: string; stage: string; autoEstimate?: boolean }) {
  const { can } = useMe();
  const boqQ = useData<Boq>(can("boq:read") ? `/projects/${projectId}/boq` : null);
  const versions = useData<S["VersionRowOut"][]>(boqQ.data ? `/boq/${boqQ.data.id}/versions` : null);
  const edits = useData<S["EditRowOut"][]>(boqQ.data ? `/boq/${boqQ.data.id}/edits` : null);
  const { busy, run } = useAction();
  const toast = useToast();
  const [local, setLocal] = useState<Boq | null>(null);
  const [pendingOps, setPendingOps] = useState<Op[]>([]);
  const [lineEdits, setLineEdits] = useState<Record<string, LineEdit>>({});
  const [reason, setReason] = useState("");
  const [drawer, setDrawer] = useState<null | { kind: "line"; id: string } | { kind: "cat"; section: string; group: string | null } | { kind: "blank"; section: string }>(null);
  const [showAccept, setShowAccept] = useState(false);
  const [note, setNote] = useState("");

  // The BOQ an action just returned, shown until the reload it starts comes back. The server's
  // copy then wins again, so changes made by someone else show up instead of being hidden.
  useEffect(() => setLocal(null), [boqQ.data]);
  const boq = local ?? boqQ.data;
  const canEdit = can("boq:edit");

  const pendingCount = pendingOps.length + Object.keys(lineEdits).length;
  const locked = !!boq && (boq.status !== "draft");
  const queue = (ops: Op[]) => setPendingOps((p) => [...p, ...ops]);

  const apply = (b: Boq) => {
    setLocal(b);
    boqQ.reload();
    versions.reload();
    edits.reload();
  };

  if (!can("boq:read")) return <Notice tone="warn">You do not have access to the BOQ.</Notice>;
  if (boqQ.loading && !boq) return <Skeleton lines={8} />;

  async function generate(replace: boolean) {
    const b = await run(() => post<Boq>(`/projects/${projectId}/boq/generate`, { replace }), "BOQ drafted from the gap register");
    if (b) {
      setPendingOps([]);
      setLineEdits({});
      apply(b);
    } else boqQ.reload();
  }

  if (!boq) {
    const atBoq = stage === "boq";
    return (
      <>
        <Empty
          title="No official BOQ yet"
          action={
            canEdit && atBoq ? (
              <button className="btn primary" disabled={busy} onClick={() => generate(false)}>
                Draft the BOQ from the gap register
              </button>
            ) : undefined
          }
        >
          {atBoq
            ? "The gap analysis is approved. Draft the official BOQ from the locked gap register. Prices come only from the price book; anything it cannot price is left for you to enter by hand."
            : "The official BOQ is drafted once the gap analysis is approved. Until then, the estimate below shows what it will roughly contain and cost."}
        </Empty>
        {!atBoq && <EstimatePanel projectId={projectId} autoStart={autoEstimate} />}
      </>
    );
  }

  const lines = boq.lines;
  const selectedLetters = boq.selected_options;
  const latest = versions.data?.[0];
  const acceptable = latest && latest.state === "issued";

  function buildOps(): Op[] {
    const ops: Op[] = [];
    for (const [id, e] of Object.entries(lineEdits)) {
      const fields: Record<string, unknown> = {};
      if (e.qty !== undefined) fields.qty = Number(e.qty);
      if (e.unit_price !== undefined) {
        fields.unit_price = e.unit_price === "" ? null : e.unit_price;
        if (e.unit_price !== "") fields.manual_price_reason = e.reason ?? "";
      }
      if (Object.keys(fields).length) ops.push({ op: "update_line", id, fields });
    }
    return [...ops, ...pendingOps];
  }
  const missingPriceReason = Object.entries(lineEdits).some(([, e]) => e.unit_price !== undefined && e.unit_price !== "" && (e.reason ?? "").trim().length < 3);

  // A refused change (most often someone else saved first) reloads the BOQ. Unsaved edits stay
  // on screen, so they can be checked against the new copy and saved again.
  async function save() {
    const b = await run(() => post<Boq>(`/boq/${boq!.id}/edit`, { draft_rev: boq!.draft_rev, reason, ops: buildOps() }), "Changes saved");
    if (b) {
      setPendingOps([]);
      setLineEdits({});
      setReason("");
      apply(b);
    } else boqQ.reload();
  }

  async function simple(path: string, body: unknown, done: string) {
    const b = await run(() => post<Boq>(`/boq/${boq!.id}/${path}`, body), done);
    if (b) apply(b);
    else boqQ.reload();
  }

  const openDoc = (fmt: string, kind = "quotation", version?: number) =>
    openApiDoc(`/api/v1/boq/${boq.id}/render?fmt=${fmt}&kind=${kind}${version ? `&version=${version}` : ""}`, true);

  // ---- grouped display ----
  const groups = boq.groups.map((g) => ({
    g,
    sections: boq.sections
      .filter((s) => s.group_id === g.id)
      .map((s) => ({ s, lines: lines.filter((l) => l.section_id === s.id) })),
  }));
  const drawerLine = drawer?.kind === "line" ? lines.find((l) => l.id === drawer.id) : undefined;

  return (
    <>
      <div className="bar">
        <div className="grow">
          <div className="row">
            <h2>{boq.quote_ref ?? "Draft quotation"}</h2>
            <Badge tone={boq.status === "accepted" ? "ok" : boq.stage === "pricing_approved" ? "accent" : boq.stage === "pricing_review" ? "warn" : undefined}>
              {boq.status === "accepted" ? "Accepted and locked" : STAGE_LABEL[boq.stage]}
            </Badge>
          </div>
          <div className="muted small num">
            {rangeText(boq.totals.subtotal_min, boq.totals.subtotal_max)} before GST
            {!boq.totals.complete && " (alternatives not chosen yet)"}
          </div>
        </div>
        <div className="row">
          <button className="btn small" onClick={() => openDoc("html")}>
            Preview
          </button>
          <button className="btn small" onClick={() => openDoc("pdf")}>
            PDF
          </button>
          <button className="btn small" onClick={() => openDoc("xlsx")}>
            Excel
          </button>
          <button className="btn small" onClick={() => openDoc("html", "summary")}>
            Summary BOQ
          </button>
        </div>
      </div>

      {(boq.blockers.length > 0 || boq.warnings.length > 0) && !locked && (
        <div className="stack" style={{ marginBottom: 14 }}>
          {boq.blockers.length > 0 && (
            <Notice tone="bad">
              <strong>{boq.blockers.length} to fix before pricing review.</strong>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {boq.blockers.slice(0, 6).map((b) => (
                  <li key={b}>{b}</li>
                ))}
                {boq.blockers.length > 6 && <li>and {boq.blockers.length - 6} more</li>}
              </ul>
            </Notice>
          )}
          {boq.warnings.length > 0 && (
            <Notice tone="warn">
              <strong>Worth a look.</strong> {boq.warnings.slice(0, 4).join(". ")}
              {boq.warnings.length > 4 && `. And ${boq.warnings.length - 4} more.`}
            </Notice>
          )}
        </div>
      )}

      {pendingCount > 0 && (
        <div className="pending">
          <strong>{pendingCount} unsaved change{pendingCount === 1 ? "" : "s"}</strong>
          <input type="text" aria-label="Reason for these changes" placeholder="Reason for these changes (kept in the history)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn primary" disabled={busy || reason.trim().length < 3 || missingPriceReason} onClick={save}>
            Save changes
          </button>
          <button className="btn" onClick={() => { setPendingOps([]); setLineEdits({}); }}>
            Discard
          </button>
          {missingPriceReason && <span className="small">A hand price needs its source. Open the line to add it.</span>}
        </div>
      )}

      {/* workflow actions */}
      {!locked && (
        <div className="row" style={{ marginBottom: 16 }}>
          {canEdit && boq.stage === "drafting" && (
            <>
              <button className="btn" disabled={busy || pendingCount > 0} onClick={() => simple("refresh-prices", { draft_rev: boq.draft_rev }, "Prices refreshed from the price book")}>
                Refresh prices
              </button>
              {latest && latest.state === "issued" && boq.outcome === "open" && (
                <button
                  className="btn"
                  disabled={busy || pendingCount > 0}
                  title="Take today's price book prices and send the BOQ for pricing approval in one step"
                  onClick={async () => {
                    const b = await run(() => post<Boq>(`/boq/${boq.id}/reprice`, { draft_rev: boq.draft_rev }));
                    if (b) {
                      apply(b);
                      toast(
                        b.submitted
                          ? `Re-priced (${b.changes?.length ?? 0} change${b.changes?.length === 1 ? "" : "s"}) and sent for pricing approval.`
                          : "Re-priced. Fix what is listed above, then submit for pricing review.",
                      );
                    } else boqQ.reload();
                  }}
                >
                  Re-price for a new version
                </button>
              )}
              <button className="btn primary" disabled={busy || pendingCount > 0 || boq.blockers.length > 0} onClick={() => simple("submit", undefined, "Submitted for pricing review")}>
                Submit for pricing review
              </button>
              <button className="btn quiet" disabled={busy} onClick={() => confirm("Start over? Every edit on this draft is replaced.") && generate(true)}>
                Draft again
              </button>
            </>
          )}
          {boq.stage === "pricing_review" && can("boq:approve_pricing") && (
            <PricingDecision
              boq={boq}
              busy={busy}
              note={note}
              setNote={setNote}
              decide={(body, done) => simple("pricing-decision", body, done)}
            />
          )}
          {boq.stage === "pricing_review" && !can("boq:approve_pricing") && <span className="muted small">Waiting for a sales head or the director to approve the pricing.</span>}
          {boq.stage === "pricing_approved" && can("boq:issue") && (
            <ConfirmButton
              className="btn primary"
              disabled={busy}
              question="Issue this as the next version? It gets the quote number and its PDF is kept as sent."
              confirmLabel="Issue"
              confirmClassName="btn primary small"
              onConfirm={async () => {
                await run(() => post(`/boq/${boq.id}/issue`, undefined, { idem: true }), "Version issued");
                boqQ.reload();
                versions.reload();
                edits.reload();
              }}
            >
              Issue as a new version
            </ConfirmButton>
          )}
        </div>
      )}
      {boq.status === "accepted" && (
        <Notice tone="ok">
          This BOQ is accepted and locked. Planning works from it.{" "}
          {canEdit && (
            <button className="btn small" disabled={busy} onClick={() => simple("reopen", { reason: "Customer asked for changes" }, "Reopened as a new draft")}>
              Reopen for changes
            </button>
          )}
        </Notice>
      )}

      {latest && <Outcome boq={boq} canEdit={canEdit} busy={busy} onChange={(b) => apply(b)} run={run} />}
      {canEdit && !locked && <SuggestedLines projectId={projectId} lines={lines} />}

      {/* the editor */}
      {groups.map(({ g, sections }) => (
        <div key={g.id}>
          <div className="grouphead">
            <h3>{g.title}</h3>
            {canEdit && !locked && (
              <button className="btn quiet small" onClick={() => queue([{ op: "add_section", group_id: g.id, title: "New section" }])}>
                Add a section
              </button>
            )}
          </div>
          {sections.map(({ s, lines: sl }) => (
            <div key={s.id}>
              <div className="sectionhead">
                {canEdit && !locked ? (
                  <input
                    type="text"
                    aria-label="Section title"
                    defaultValue={s.title}
                    style={{ maxWidth: 420, fontWeight: 600 }}
                    onBlur={(e) => e.target.value !== s.title && e.target.value.trim() && queue([{ op: "update_section", id: s.id, title: e.target.value.trim() }])}
                  />
                ) : (
                  <span>{s.title}</span>
                )}
                {canEdit && !locked && (
                  <>
                    <button className="btn quiet small" onClick={() => setDrawer({ kind: "cat", section: s.id, group: null })}>
                      Add from catalogue
                    </button>
                    <button className="btn quiet small" onClick={() => setDrawer({ kind: "blank", section: s.id })}>
                      Add by hand
                    </button>
                    {sl.length === 0 && (
                      <button className="btn quiet small" onClick={() => queue([{ op: "delete_section", id: s.id }])}>
                        Delete section
                      </button>
                    )}
                  </>
                )}
              </div>
              {sl.length > 0 && (
                <table className="boq">
                  <thead>
                    <tr>
                      <th style={{ width: 54 }}>Sr N</th>
                      <th>Component</th>
                      <th style={{ width: 84 }}>Qty</th>
                      <th style={{ width: 130 }}>Price</th>
                      <th style={{ width: 130 }} className="r">Amount</th>
                      <th style={{ width: 170 }} />
                    </tr>
                  </thead>
                  <tbody>
                    {sl.map((l, idx) => {
                      const e = lineEdits[l.id] ?? {};
                      const blocked = l.flags.some((f) => ["no_price", "price_expired", "zero_qty"].includes(f));
                      const chosen = !!l.option_group && selectedLetters[l.option_group] === l.letter;
                      return (
                        <tr key={l.id} className={`${l.option_group ? "opt" : ""} ${chosen ? "chosen" : ""} ${blocked ? "blocked" : l.flags.length ? "flagged" : ""}`}>
                          <td>
                            <span className="ref">{l.ref}</span>
                            {l.option_group && (
                              <div>
                                <label className="small">
                                  <input
                                    type="radio"
                                    name={`opt-${l.option_group}`}
                                    checked={chosen}
                                    disabled={!canEdit || locked}
                                    onChange={() => queue([{ op: "set_option", group: l.option_group, letter: l.letter }])}
                                  />{" "}
                                  Chosen
                                </label>
                              </div>
                            )}
                          </td>
                          <td>
                            <div className="title">{l.title}</div>
                            {l.description && <div className="sub">{l.description}</div>}
                            {(l.inclusions?.length ?? 0) > 0 && <div className="sub">{l.inclusions!.slice(0, 2).join("; ")}{l.inclusions!.length > 2 ? `; +${l.inclusions!.length - 2} more` : ""}</div>}
                            <div className="flags">
                              {l.flags.map((f) => (FLAG[f] ? <Badge key={f} tone={FLAG[f][1]}>{FLAG[f][0]}</Badge> : null))}
                              {l.option_group && <Badge>Alternative</Badge>}
                              {l.source.kind === "recommended" && <Badge tone="accent">Recommended</Badge>}
                            </div>
                          </td>
                          <td>
                            <input className={`cell${e.qty !== undefined ? " dirty" : ""}`} type="number" min={0} aria-label={`Quantity for ${l.title}`} disabled={!canEdit || locked}
                              value={e.qty ?? String(l.qty)} onChange={(ev) => setLineEdits({ ...lineEdits, [l.id]: { ...e, qty: ev.target.value } })} />
                          </td>
                          <td>
                            <input className={`cell${e.unit_price !== undefined ? " dirty" : ""}`} type="text" inputMode="decimal" aria-label={`Price for ${l.title}`} disabled={!canEdit || locked}
                              placeholder={l.hint_price ? `was ${l.hint_price}` : "enter price"} value={e.unit_price ?? l.unit_price ?? ""}
                              onChange={(ev) => setLineEdits({ ...lineEdits, [l.id]: { ...e, unit_price: ev.target.value } })} />
                            {l.margin_pct !== null && l.margin_pct !== undefined && e.unit_price === undefined && (
                              <div className={`small${l.flags.includes("low_margin") ? "" : " muted"}`} style={l.flags.includes("low_margin") ? { color: "var(--warn)" } : undefined}>
                                margin {l.margin_pct}%
                              </div>
                            )}
                            {e.unit_price !== undefined && e.unit_price !== "" && (
                              <input className="cell" style={{ marginTop: 4, textAlign: "left", fontFamily: "inherit" }} type="text" aria-label="Source of this price" placeholder="Source of this price"
                                value={e.reason ?? ""} onChange={(ev) => setLineEdits({ ...lineEdits, [l.id]: { ...e, reason: ev.target.value } })} />
                            )}
                          </td>
                          <td className="num">{l.amount ? money(l.amount) : ""}</td>
                          <td className="acts">
                            <button className="btn quiet small" onClick={() => setDrawer({ kind: "line", id: l.id })}>
                              {canEdit && !locked ? "Edit" : "Details"}
                            </button>
                            {canEdit && !locked && (
                              <>
                                <button className="btn quiet small" aria-label="Move up" disabled={idx === 0} onClick={() => queue([{ op: "move_line", id: l.id, section_id: s.id, index: idx - 1 }])}>
                                  Up
                                </button>
                                <button className="btn quiet small" aria-label="Move down" disabled={idx === sl.length - 1} onClick={() => queue([{ op: "move_line", id: l.id, section_id: s.id, index: idx + 1 }])}>
                                  Down
                                </button>
                                <button className="btn quiet small" aria-label={`Delete ${l.title}`} onClick={() => queue([{ op: "delete_line", id: l.id }])}>
                                  Delete
                                </button>
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      ))}

      <dl className="totals">
        <dt>Sub total</dt>
        <dd>{rangeText(boq.totals.subtotal_min, boq.totals.subtotal_max)}</dd>
        <dt>GST</dt>
        <dd>{rangeText(boq.totals.gst_min, boq.totals.gst_max)}</dd>
        <dt>Total</dt>
        <dd className="grand">{rangeText(boq.totals.total_min, boq.totals.total_max)}</dd>
      </dl>
      <p className="stepnote" style={{ textAlign: "right" }}>
        Alternatives are never added together. The quotation prints totals only if you switch them on.
      </p>

      <SettingsPanel boq={boq} queue={queue} locked={locked} />

      {/* versions and acceptance */}
      <div className="section">
        <h2>Versions</h2>
        {!versions.data?.length ? (
          <p className="stepnote">Nothing issued yet. Issue a version once the pricing is approved. Each issue creates v1, v2 and so on, and the customer accepts one.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Version</th>
                <th>What changed</th>
                <th>State</th>
                <th className="right">Issued</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {versions.data.map((v) => (
                <tr key={v.number}>
                  <td data-label="Version">
                    v{v.number} <span className="muted small mono">{v.quote_ref}</span>
                  </td>
                  <td data-label="What changed">{v.change_summary}</td>
                  <td data-label="State">
                    <Badge tone={v.state === "accepted" ? "ok" : v.state === "issued" ? "accent" : undefined}>{v.state}</Badge>
                    {v.po_number && <div className="muted small">PO {v.po_number}</div>}
                  </td>
                  <td data-label="Issued" className="right">{dateTime(v.issued_at)}</td>
                  <td className="right">
                    <button className="btn quiet small" onClick={() => openDoc("pdf", "quotation", v.number)}>PDF</button>
                    <button className="btn quiet small" onClick={() => openDoc("xlsx", "quotation", v.number)}>Excel</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {(versions.data?.length ?? 0) > 1 && <CompareVersions boqId={boq.id} numbers={versions.data!.map((v) => v.number)} />}
        {acceptable && can("boq:accept") && !showAccept && (
          <button className="btn primary" style={{ marginTop: 12 }} onClick={() => setShowAccept(true)}>
            The customer accepted: record the purchase order
          </button>
        )}
        {showAccept && acceptable && latest && <Accept boq={boq} version={latest.number} onDone={() => { setShowAccept(false); boqQ.reload(); versions.reload(); }} />}
      </div>

      <div className="section">
        <h2>History</h2>
        <table className="table">
          <tbody>
            {(edits.data ?? []).slice(0, 12).map((e, i) => (
              <tr key={i}>
                <td data-label="When" className="small muted" style={{ whiteSpace: "nowrap" }}>{dateTime(e.at)}</td>
                <td data-label="What">
                  {e.reason}
                  {e.detail.length > 0 && <div className="muted small">{e.detail.slice(0, 3).join("; ")}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {drawerLine && <LineDrawer line={drawerLine} boq={boq} onClose={() => setDrawer(null)} queue={queue} />}
      {drawer?.kind === "cat" && (
        <CatalogueDrawer boq={boq} sectionId={drawer.section} optionGroup={drawer.group} pending={pendingCount > 0} onClose={() => setDrawer(null)} onAdded={(b) => { setDrawer(null); apply(b); }} />
      )}
      {drawer?.kind === "blank" && <BlankLineDrawer sectionId={drawer.section} onClose={() => setDrawer(null)} queue={queue} />}
    </>
  );
}

const CHANGE_LABEL: Record<string, string> = {
  title: "Title",
  qty: "Quantity",
  unit_price: "Price",
  gst_rate: "GST %",
  option_group: "Alternative group",
};

function changeText(field: string, [was, now]: [string, string]) {
  const show = (v: string) => (v === "None" ? "none" : field === "unit_price" ? money(v) : v);
  return `${CHANGE_LABEL[field] ?? field}: ${show(was)} to ${show(now)}`;
}

function CompareVersions({ boqId, numbers }: { boqId: string; numbers: number[] }) {
  // numbers arrive newest first; default to the latest against the one before it
  const [newer, setNewer] = useState(numbers[0]);
  const [older, setOlder] = useState(numbers[1]);
  const res = useData<S["CompareOut"]>(older !== newer ? `/boq/${boqId}/compare?older=${older}&newer=${newer}` : null);
  const pick = (id: string, label: string, value: number, set: (n: number) => void) => (
    <Field id={id} label={label}>
      <select id={id} value={value} onChange={(e) => set(Number(e.target.value))}>
        {numbers.map((n) => (
          <option key={n} value={n}>
            v{n}
          </option>
        ))}
      </select>
    </Field>
  );
  const c = res.data;
  return (
    <div className="stack" style={{ marginTop: 16 }}>
      <h3>Compare versions</h3>
      <div className="row">
        {pick("cmp-old", "From", older, setOlder)}
        {pick("cmp-new", "To", newer, setNewer)}
      </div>
      {older === newer ? (
        <p className="stepnote">Pick two different versions.</p>
      ) : res.loading && !c ? (
        <Skeleton lines={3} />
      ) : res.error ? (
        <Notice tone="bad">{res.error}</Notice>
      ) : c ? (
        <>
          <p>
            <strong>{c.summary}</strong>{" "}
            <span className="muted">
              Total v{c.older.number}: {rangeText(String(c.older.totals.total_min), String(c.older.totals.total_max))}. Total v{c.newer.number}:{" "}
              {rangeText(String(c.newer.totals.total_min), String(c.newer.totals.total_max))}.
            </span>
          </p>
          <table className="table">
            <tbody>
              {c.added.map((t, i) => (
                <tr key={`a${i}`}>
                  <td data-label="Change"><Badge tone="ok">Added</Badge></td>
                  <td data-label="Line">{t}</td>
                </tr>
              ))}
              {c.removed.map((t, i) => (
                <tr key={`r${i}`}>
                  <td data-label="Change"><Badge tone="bad">Removed</Badge></td>
                  <td data-label="Line">{t}</td>
                </tr>
              ))}
              {c.changed.map((x, i) => (
                <tr key={`c${i}`}>
                  <td data-label="Change"><Badge tone="accent">Changed</Badge></td>
                  <td data-label="Line">
                    {String(x.line)}
                    <div className="muted small">
                      {Object.entries(x)
                        .filter(([k]) => k !== "line")
                        .map(([k, v]) => changeText(k, v as [string, string]))
                        .join("; ")}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </div>
  );
}

function Accept({ boq, version, onDone }: { boq: Boq; version: number; onDone: () => void }) {
  const ver = useData<S["VersionViewOut"]>(`/boq/${boq.id}/versions/${version}`);
  const { busy, run } = useAction();
  const [po, setPo] = useState("");
  const [poDate, setPoDate] = useState(new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date()));
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const groups = useMemo(() => {
    const m: Record<string, { letter: string; title: string }[]> = {};
    for (const l of (ver.data?.lines ?? []) as { option_group?: string; letter?: string; title: string }[]) {
      if (l.option_group && l.letter) (m[l.option_group] ??= []).push({ letter: l.letter, title: l.title });
    }
    return m;
  }, [ver.data]);
  const ready = po.trim().length >= 3 && Object.keys(groups).every((g) => chosen[g] || ver.data?.selected_options?.[g]);
  return (
    <div className="stack" style={{ maxWidth: 560, marginTop: 14 }}>
      <h3>Accept v{version}</h3>
      <Field id="po" label="Customer purchase order number">
        <input id="po" type="text" value={po} onChange={(e) => setPo(e.target.value)} />
      </Field>
      <Field id="pod" label="Purchase order date">
        <input id="pod" type="date" value={poDate} onChange={(e) => setPoDate(e.target.value)} />
      </Field>
      {Object.entries(groups).map(([g, opts]) => (
        <Field key={g} id={`og-${g}`} label="Which alternative did the customer choose?">
          <select id={`og-${g}`} value={chosen[g] ?? ver.data?.selected_options?.[g] ?? ""} onChange={(e) => setChosen({ ...chosen, [g]: e.target.value })}>
            <option value="">Choose one</option>
            {opts.map((o) => (
              <option key={o.letter} value={o.letter}>
                {o.letter}: {o.title}
              </option>
            ))}
          </select>
        </Field>
      ))}
      <div className="row">
        <button
          className="btn primary"
          disabled={busy || !ready}
          onClick={async () => {
            const r = await run(() => post(`/boq/${boq.id}/versions/${version}/accept`, { po_number: po, po_date: poDate, selected_options: chosen }, { idem: true }), "BOQ accepted and locked");
            if (r !== undefined) onDone();
          }}
        >
          Accept and lock
        </button>
        <button className="btn quiet" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}


/** Approve or send back the pricing. Lines under the minimum margin are accepted one by one, with
 * a reason (ADR 0028). */
function PricingDecision({
  boq,
  busy,
  note,
  setNote,
  decide,
}: {
  boq: Boq;
  busy: boolean;
  note: string;
  setNote: (v: string) => void;
  decide: (body: Record<string, unknown>, done: string) => Promise<void>;
}) {
  const low = boq.lines.filter((l) => l.flags.includes("low_margin"));
  const [acked, setAcked] = useState<string[]>([]);
  const allAcked = low.every((l) => acked.includes(l.id));
  return (
    <div className="stack" style={{ width: "100%" }}>
      {low.length > 0 && (
        <Notice tone="warn">
          <strong>
            {low.length} line{low.length === 1 ? " is" : "s are"} under the {boq.min_margin_pct}% minimum margin.
          </strong>{" "}
          Accept each one and say why in the note.
          <div className="stack" style={{ marginTop: 8 }}>
            {low.map((l) => (
              <Check key={l.id} checked={acked.includes(l.id)} onChange={(v) => setAcked(v ? [...acked, l.id] : acked.filter((x) => x !== l.id))}>
                <span className="mono">{l.ref}</span> {l.title}: margin {l.margin_pct}%
              </Check>
            ))}
          </div>
        </Notice>
      )}
      <div className="row">
        <input
          type="text"
          aria-label="Note"
          placeholder={low.length ? "Why the low margins are acceptable" : "Note (required to send back)"}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={{ maxWidth: 360, flex: 1 }}
        />
        <button
          className="btn primary"
          disabled={busy || (low.length > 0 && (!allAcked || note.trim().length < 5))}
          onClick={() => decide({ approve: true, note: note || null, margin_ack: acked }, "Pricing approved")}
        >
          Approve pricing
        </button>
        <button className="btn" disabled={busy || note.trim().length < 3} onClick={() => decide({ approve: false, note }, "Sent back")}>
          Send back
        </button>
      </div>
    </div>
  );
}

const LOSS_REASONS: { id: string; label: string }[] = [
  { id: "price", label: "Our price was too high" },
  { id: "competitor", label: "They chose a competitor" },
  { id: "budget", label: "No budget" },
  { id: "timing", label: "Not now, maybe later" },
  { id: "scope", label: "The scope did not fit" },
  { id: "no_decision", label: "They never decided" },
  { id: "relationship", label: "The relationship" },
  { id: "other", label: "Something else" },
];

/** Won or lost, with the reason: every quote ends one way or the other, and the learning module
 * learns from both. A win is recorded by accepting a version with the purchase order. */
function Outcome({
  boq,
  canEdit,
  busy,
  onChange,
  run,
}: {
  boq: Boq;
  canEdit: boolean;
  busy: boolean;
  onChange: (b: Boq) => void;
  run: <T>(fn: () => Promise<T>, done?: string) => Promise<T | undefined>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("price");
  const [competitor, setCompetitor] = useState("");
  const [note, setNote] = useState("");
  if (boq.outcome === "won") return null; // shown as accepted and locked
  if (boq.outcome === "lost") {
    return (
      <Notice tone="warn">
        <strong>Lost:</strong> {LOSS_REASONS.find((r) => r.id === boq.outcome_reason)?.label ?? boq.outcome_reason}
        {boq.outcome_at ? `, recorded ${date(boq.outcome_at)}` : ""}. The BOQ is closed.
        {canEdit && (
          <div className="row" style={{ marginTop: 8 }}>
            <input type="text" aria-label="Why it is open again" placeholder="Why it is open again" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, maxWidth: 360 }} />
            <button
              className="btn small"
              disabled={busy || note.trim().length < 5}
              onClick={async () => {
                const b = await run(() => post<Boq>(`/boq/${boq.id}/outcome`, { outcome: "open", note: note.trim() }), "Open again");
                if (b) onChange(b);
              }}
            >
              Open the quote again
            </button>
          </div>
        )}
      </Notice>
    );
  }
  if (!canEdit || boq.status !== "draft") return null;
  if (!open) {
    return (
      <div style={{ marginBottom: 16 }}>
        <button className="btn quiet small" onClick={() => setOpen(true)}>
          The customer said no
        </button>
      </div>
    );
  }
  return (
    <div className="section stack">
      <h3>Record a lost quote</h3>
      <div className="form-grid">
        <Field id="lost-reason" label="Why">
          <select id="lost-reason" value={reason} onChange={(e) => setReason(e.target.value)}>
            {LOSS_REASONS.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        {reason === "competitor" && (
          <Field id="lost-comp" label="Which competitor">
            <input id="lost-comp" value={competitor} onChange={(e) => setCompetitor(e.target.value)} />
          </Field>
        )}
        <div className="wide">
          <Field id="lost-note" label="What happened" hint={reason === "other" ? "Needed for Something else." : "Optional."}>
            <textarea id="lost-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </div>
      </div>
      <div className="row">
        <button
          className="btn danger"
          disabled={busy || (reason === "other" && note.trim().length < 5)}
          onClick={async () => {
            const b = await run(
              () => post<Boq>(`/boq/${boq.id}/outcome`, { outcome: "lost", reason, competitor: competitor || null, note: note.trim() || null }),
              "Recorded as lost",
            );
            if (b) {
              setOpen(false);
              onChange(b);
            }
          }}
        >
          Record as lost
        </button>
        <button className="btn quiet" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Lines an approved learning model expects from the audit findings. Advice only: a person adds
 * a line by hand if it belongs. Hidden while no model is approved. */
function SuggestedLines({ projectId, lines }: { projectId: string; lines: Line[] }) {
  const s = useData<S["SuggestionsOut"]>(`/ml/projects/${projectId}/suggested-lines`);
  if (!s.data?.available || s.data.lines.length === 0) return null;
  const have = new Set(lines.map((l) => l.title.trim().toLowerCase()));
  const missing = s.data.lines.filter((x) => !have.has(x.title.trim().toLowerCase()));
  if (missing.length === 0) return null;
  return (
    <Notice>
      <strong>The learning module expects these lines too</strong> (model {s.data.model}, advice only):
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {missing.slice(0, 8).map((x) => (
          <li key={x.label}>
            {x.title} <span className="muted small">({Math.round(x.probability * 100)} percent of similar audits)</span>
          </li>
        ))}
      </ul>
    </Notice>
  );
}
