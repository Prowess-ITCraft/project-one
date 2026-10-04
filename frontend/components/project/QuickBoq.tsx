"use client";
import { useEffect, useState } from "react";
import { FileArrowUp } from "@phosphor-icons/react";
import { ApiError, post, put, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Field, Notice } from "@/components/ui";
import { EstimatePanel } from "@/components/project/EstimatePanel";

const BEFORE_BOQ = ["audit_intake", "current_infra", "ideal_infra", "gap_analysis"];

/** One step from a PrismSuite report to a BOQ estimate: upload the report, answer the few
 * questions the rules need, and the estimate is drafted with today's price book. The approvals
 * are untouched; the official BOQ still comes from the approved gap register. */
export function QuickBoq({ projectId, stage, onImported }: { projectId: string; stage: string; onImported?: () => void }) {
  const { can } = useMe();
  const allowed = can("prismsuite:import") && can("brief:write") && can("boq:estimate") && BEFORE_BOQ.includes(stage);
  const brief = useData<S["BriefOut"] | null>(allowed ? `/projects/${projectId}/brief` : null);
  const imports = useData<S["ImportOut"][]>(allowed ? `/prismsuite/imports/by-project/${projectId}` : null);
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafted, setDrafted] = useState(0);
  const [f, setF] = useState({ company_size: "small", budget_tier: "standard", sites: "1", users_now: "", users_12m: "" });

  useEffect(() => {
    const b = brief.data;
    if (!b) return;
    setF({
      company_size: b.company_size,
      budget_tier: b.budget_tier,
      sites: String(b.sites),
      users_now: b.users_now?.toString() ?? "",
      users_12m: b.users_12m?.toString() ?? "",
    });
  }, [brief.data]);

  if (!allowed) return null;

  const current = (imports.data ?? [])
    .filter((i) => (i.kind ?? "baseline") === "baseline" && ["in_review", "approved"].includes(i.status))
    .sort((a, b) => b.revision - a.revision)[0];
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    try {
      if (file) {
        setStep("Uploading and reading the report");
        const form = new FormData();
        form.append("file", file);
        form.append("purpose", "audit_report");
        form.append("project_id", projectId);
        const up = await post<S["FileOut"]>("/files", undefined, { form });
        try {
          await post("/prismsuite/imports", { project_id: projectId, file_id: up.id, kind: "baseline" }, { idem: true });
        } catch (e) {
          // The same file again: keep the import already there and carry on.
          if (!(e instanceof ApiError && e.code === "already_imported")) throw e;
        }
        setFile(null);
        imports.reload();
        onImported?.();
      }
      setStep("Saving the answers");
      const b = brief.data;
      await put(`/projects/${projectId}/brief`, {
        version: b?.version ?? undefined,
        company_size: f.company_size,
        budget_tier: f.budget_tier,
        sites: Number(f.sites) || 1,
        users_now: f.users_now ? Number(f.users_now) : null,
        users_12m: f.users_12m ? Number(f.users_12m) : null,
        preferred_brands: b?.preferred_brands ?? [],
        excluded_brands: b?.excluded_brands ?? [],
        budget_ceiling: b?.budget_ceiling ?? null,
        category_budgets: b?.category_budgets ?? {},
        keep_assets: b?.keep_assets ?? [],
        compliance: b?.compliance ?? [],
        notes: b?.notes ?? null,
      });
      brief.reload();
      setDrafted((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Try again.");
    } finally {
      setStep(null);
    }
  }

  if (!open) {
    return (
      <div className="estimate-ready">
        <div>
          <h3>BOQ from a PrismSuite report</h3>
          <p className="muted small">Upload the report, answer five questions, and get a priced BOQ estimate as PDF or Excel.</p>
        </div>
        <button className="btn primary" onClick={() => setOpen(true)}>
          <FileArrowUp size={18} aria-hidden /> Upload report and draft BOQ
        </button>
      </div>
    );
  }

  const ready = !!file || !!current;
  return (
    <>
      <form className="section" onSubmit={submit}>
        <div className="row between">
          <h2>Upload report and draft BOQ</h2>
          <button type="button" className="btn quiet small" onClick={() => setOpen(false)}>
            Close
          </button>
        </div>
        <p className="lede">
          Prices come from the price book, entered by hand in the Catalogue. Anything without a price is left blank for you to fill in.
        </p>
        <Field
          id="qb-file"
          label="PrismSuite report (.docx or .json)"
          hint={current ? `Leave empty to use revision ${current.revision}, already imported.` : undefined}
        >
          <input id="qb-file" type="file" accept=".docx,.json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <div className="grid3">
          <Field id="qb-size" label="Company size">
            <select id="qb-size" value={f.company_size} onChange={set("company_size")}>
              <option value="micro">Micro, up to 10 people</option>
              <option value="small">Small, 11 to 50</option>
              <option value="medium">Medium, 51 to 250</option>
              <option value="large">Large, over 250</option>
            </select>
          </Field>
          <Field id="qb-tier" label="Budget tier" hint="Essential keeps only what the audit needs.">
            <select id="qb-tier" value={f.budget_tier} onChange={set("budget_tier")}>
              <option value="essential">Essential</option>
              <option value="standard">Standard</option>
              <option value="premium">Premium</option>
            </select>
          </Field>
          <Field id="qb-sites" label="Sites">
            <input id="qb-sites" type="number" min={1} value={f.sites} onChange={set("sites")} />
          </Field>
          <Field id="qb-un" label="Users now">
            <input id="qb-un" type="number" min={1} value={f.users_now} onChange={set("users_now")} />
          </Field>
          <Field id="qb-u12" label="Users in 12 months" hint="Used to size firewalls and licences.">
            <input id="qb-u12" type="number" min={1} value={f.users_12m} onChange={set("users_12m")} />
          </Field>
        </div>
        {error && <Notice tone="bad">{error}</Notice>}
        <button className="btn primary" disabled={!ready || !!step}>
          {step ?? "Upload and draft BOQ"}
        </button>
        {!ready && <p className="muted small">Choose the report file first.</p>}
      </form>
      {drafted > 0 && <EstimatePanel key={drafted} projectId={projectId} autoStart />}
    </>
  );
}
