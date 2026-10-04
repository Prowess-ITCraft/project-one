"use client";
import { useEffect, useState } from "react";
import { ApiError, get, money, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Notice } from "@/components/ui";

type Estimate = {
  basis: { audit_revision: number; audit_approved: boolean; company_size: string; budget_tier: string };
  gaps: { code: string; title: string; priority: string; status: string }[];
  sections: { id: string; title: string }[];
  lines: (S["LineOut"] & { ref?: string; amount?: string | null; section_id: string })[];
  totals: { total_min: string; total_max: string; subtotal_min: string; subtotal_max: string; complete: boolean };
  unmatched: { gap: string; title: string }[];
  unpriced: { item: string; state: string }[];
};

const range = (a: string, b: string) => (a === b ? money(a) : `${money(a)} to ${money(b)}`);

/** What the estimate needs, ticked off as it arrives. Shown wherever the documents are added. */
export function EstimateReadiness({ projectId, onOpen }: { projectId: string; onOpen?: () => void }) {
  const { can } = useMe();
  const brief = useData<S["BriefOut"] | null>(`/projects/${projectId}/brief`);
  const imports = useData<S["ImportOut"][]>(can("prismsuite:review") ? `/prismsuite/imports/by-project/${projectId}` : null);
  if (!can("boq:edit")) return null;
  const report = imports.data?.some((i) => (i.kind ?? "baseline") === "baseline" && ["in_review", "approved"].includes(i.status));
  const briefDone = !!brief.data;
  const ready = briefDone && (report ?? true);
  return (
    <div className="estimate-ready">
      <div>
        <h3>BOQ estimate</h3>
        <ul className="checks">
          {imports.data !== null && (
            <li data-done={report ? "yes" : "no"}>{report ? "PrismSuite report read" : "Upload the PrismSuite report (Audit intake)"}</li>
          )}
          <li data-done={briefDone ? "yes" : "no"}>{briefDone ? "Questionnaire saved" : "Fill in the Questionnaire"}</li>
        </ul>
        <p className="muted small">
          {ready
            ? "Everything needed is in. The estimate does not wait for approvals; the official BOQ still does."
            : "As soon as both are in, a BOQ estimate can be drafted in one click."}
        </p>
      </div>
      {onOpen && (
        <button className="btn primary" disabled={!ready} onClick={onOpen}>
          Draft BOQ estimate
        </button>
      )}
    </div>
  );
}

/** Drafts the BOQ straight from the report and questionnaire, saved nowhere (backend
 * GET /projects/{id}/boq/estimate). Labelled as an estimate everywhere, documents included. */
export function EstimatePanel({ projectId, autoStart }: { projectId: string; autoStart?: boolean }) {
  const { can } = useMe();
  const [est, setEst] = useState<Estimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function draft() {
    setBusy(true);
    setError(null);
    try {
      setEst(await get<Estimate>(`/projects/${projectId}/boq/estimate`));
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "brief_required"
          ? "Fill in the Questionnaire first: the company size and budget decide which rules apply."
          : e instanceof ApiError && e.code === "no_audit"
            ? "Upload the PrismSuite report on the Audit intake tab first."
            : e instanceof ApiError
              ? e.message
              : "Something went wrong. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (autoStart) void draft();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart]);
  if (!can("boq:edit")) return null;

  const doc = (fmt: "pdf" | "xlsx", kind = "quotation") =>
    window.open(`/api/v1/projects/${projectId}/boq/estimate?fmt=${fmt}&kind=${kind}`, "_blank");

  return (
    <div className="section estimate">
      <div className="row between">
        <h2>
          BOQ estimate <Badge tone="warn">Not approved</Badge>
        </h2>
        <button className="btn" disabled={busy} onClick={draft}>
          {busy ? "Drafting" : est ? "Draft again" : "Draft BOQ estimate"}
        </button>
      </div>
      <p className="muted">
        Worked out straight from the PrismSuite report and the Questionnaire, with today&apos;s price book. Nothing is saved and no approval is skipped: the
        official BOQ is drafted once the gap analysis is approved. Use this to talk numbers early, not as a quotation.
      </p>
      {error && <Notice tone="warn">{error}</Notice>}
      {est && (
        <>
          <dl className="kv">
            <dt>Based on</dt>
            <dd>
              Audit revision {est.basis.audit_revision} ({est.basis.audit_approved ? "approved" : "not reviewed yet"}), {est.basis.company_size} company,{" "}
              {est.basis.budget_tier} budget
            </dd>
            <dt>Gaps found</dt>
            <dd>
              {est.gaps.filter((g) => g.status === "open").length} to fix
              {est.gaps.some((g) => g.status === "verify") ? `, ${est.gaps.filter((g) => g.status === "verify").length} to check on site` : ""}
            </dd>
            <dt>Estimated total</dt>
            <dd>
              <strong>{range(est.totals.total_min, est.totals.total_max)}</strong> with GST
              {!est.totals.complete && <span className="muted"> (a range, because alternatives are not chosen yet)</span>}
            </dd>
          </dl>
          {est.unpriced.length > 0 && (
            <Notice tone="warn">
              {est.unpriced.length} item{est.unpriced.length === 1 ? " has" : "s have"} no current price, so the total is too low:{" "}
              {est.unpriced.map((u) => u.item).join(", ")}.
            </Notice>
          )}
          {est.unmatched.length > 0 && (
            <Notice>
              No product matched {est.unmatched.length === 1 ? "one gap" : `${est.unmatched.length} gaps`}: {est.unmatched.map((u) => u.title).join(", ")}.
            </Notice>
          )}
          <div className="row" style={{ margin: "12px 0" }}>
            <button className="btn quiet small" onClick={() => doc("pdf")}>
              Estimate as PDF
            </button>
            <button className="btn quiet small" onClick={() => doc("xlsx")}>
              Estimate as Excel
            </button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Sr</th>
                <th>Component</th>
                <th className="right">Qty</th>
                <th className="right">Price</th>
                <th className="right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {est.sections.map((s) => {
                const rows = est.lines.filter((l) => l.section_id === s.id);
                if (!rows.length) return null;
                return [
                  <tr key={s.id} className="group-row">
                    <td colSpan={5}>{s.title}</td>
                  </tr>,
                  ...rows.map((l) => (
                    <tr key={l.id}>
                      <td data-label="Sr" className="mono">
                        {l.ref}
                      </td>
                      <td data-label="Component">{l.title}</td>
                      <td data-label="Qty" className="right">
                        {String(l.qty)}
                      </td>
                      <td data-label="Price" className="right">
                        {l.unit_price ? money(l.unit_price) : <span className="muted">no price</span>}
                      </td>
                      <td data-label="Amount" className="right">
                        {l.amount ? money(l.amount) : ""}
                      </td>
                    </tr>
                  )),
                ];
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
