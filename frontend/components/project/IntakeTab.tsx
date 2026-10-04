"use client";
import { useEffect, useState } from "react";
import { put, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Field, Notice, Skeleton, useAction } from "@/components/ui";
import { toList } from "@/components/kit";
import { EstimateReadiness } from "@/components/project/EstimatePanel";

type Brief = S["BriefOut"] | null;

export function IntakeTab({ projectId, onEstimate }: { projectId: string; onEstimate?: () => void }) {
  const { can } = useMe();
  const brief = useData<Brief>(`/projects/${projectId}/brief`);
  const { busy, run } = useAction();
  const editable = can("brief:write");
  const [f, setF] = useState({
    company_size: "small",
    budget_tier: "standard",
    users_now: "",
    users_12m: "",
    sites: "1",
    preferred: "",
    excluded: "",
    ceiling: "",
    keep: "",
    compliance: "",
    notes: "",
  });

  useEffect(() => {
    const b = brief.data;
    if (!b) return;
    setF({
      company_size: b.company_size,
      budget_tier: b.budget_tier,
      users_now: b.users_now?.toString() ?? "",
      users_12m: b.users_12m?.toString() ?? "",
      sites: String(b.sites),
      preferred: b.preferred_brands.join(", "),
      excluded: b.excluded_brands.join(", "),
      ceiling: b.budget_ceiling ?? "",
      keep: b.keep_assets.join("\n"),
      compliance: b.compliance.join(", "),
      notes: b.notes ?? "",
    });
  }, [brief.data]);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    const body = {
      version: brief.data?.version ?? undefined,
      company_size: f.company_size,
      budget_tier: f.budget_tier,
      users_now: f.users_now ? Number(f.users_now) : null,
      users_12m: f.users_12m ? Number(f.users_12m) : null,
      sites: Number(f.sites) || 1,
      preferred_brands: toList(f.preferred),
      excluded_brands: toList(f.excluded),
      budget_ceiling: f.ceiling || null,
      category_budgets: brief.data?.category_budgets ?? {}, // set through the API; kept as is
      keep_assets: toList(f.keep),
      compliance: toList(f.compliance),
      notes: f.notes || null,
    };
    await run(() => put(`/projects/${projectId}/brief`, body), "Questionnaire saved");
    brief.reload();
  }

  if (brief.loading && !brief.data && brief.data !== null) return <Skeleton lines={6} />;
  return (
    <>
    <form onSubmit={save} style={{ maxWidth: 760 }}>
      <p className="stepnote" style={{ marginBottom: 16 }}>
        What the customer wants and can spend. The company size and budget tier choose which ideal-infrastructure
        rules apply, and the brands and budget steer the BOQ.
      </p>
      {!brief.data && <Notice>Nothing saved yet. The ideal infrastructure cannot be built without this.</Notice>}
      <div className="grid3" style={{ marginTop: 14 }}>
        <Field id="size" label="Company size">
          <select id="size" value={f.company_size} onChange={set("company_size")} disabled={!editable}>
            <option value="micro">Micro, up to 10 people</option>
            <option value="small">Small, 11 to 50</option>
            <option value="medium">Medium, 51 to 250</option>
            <option value="large">Large, over 250</option>
          </select>
        </Field>
        <Field id="tier" label="Budget tier" hint="Essential keeps only what the audit needs.">
          <select id="tier" value={f.budget_tier} onChange={set("budget_tier")} disabled={!editable}>
            <option value="essential">Essential</option>
            <option value="standard">Standard</option>
            <option value="premium">Premium</option>
          </select>
        </Field>
        <Field id="sites" label="Sites">
          <input id="sites" type="number" min={1} value={f.sites} onChange={set("sites")} disabled={!editable} />
        </Field>
        <Field id="un" label="Users now">
          <input id="un" type="number" min={1} value={f.users_now} onChange={set("users_now")} disabled={!editable} />
        </Field>
        <Field id="u12" label="Users in 12 months" hint="Used to size firewalls and licences.">
          <input id="u12" type="number" min={1} value={f.users_12m} onChange={set("users_12m")} disabled={!editable} />
        </Field>
        <Field id="ceil" label="Budget ceiling (INR)" hint="Optional. The BOQ warns when it goes over.">
          <input id="ceil" type="text" inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,2})?" value={f.ceiling} onChange={set("ceiling")} disabled={!editable} />
        </Field>
      </div>
      <div className="grid2">
        <Field id="pref" label="Preferred brands" hint="Separate with commas.">
          <input id="pref" type="text" value={f.preferred} onChange={set("preferred")} disabled={!editable} />
        </Field>
        <Field id="excl" label="Excluded brands" hint="These are never proposed.">
          <input id="excl" type="text" value={f.excluded} onChange={set("excluded")} disabled={!editable} />
        </Field>
        <Field id="keep" label="Assets to keep" hint="One per line.">
          <textarea id="keep" value={f.keep} onChange={set("keep")} disabled={!editable} />
        </Field>
        <Field id="comp" label="Compliance needs" hint="For example ISO 27001, RBI.">
          <input id="comp" type="text" value={f.compliance} onChange={set("compliance")} disabled={!editable} />
        </Field>
      </div>
      <Field id="notes" label="Notes">
        <textarea id="notes" value={f.notes} onChange={set("notes")} disabled={!editable} />
      </Field>
      {editable && (
        <button className="btn primary" disabled={busy}>
          {busy ? "Saving" : brief.data ? "Save changes" : "Save questionnaire"}
        </button>
      )}
    </form>
    <EstimateReadiness key={brief.data?.version ?? "none"} projectId={projectId} onOpen={onEstimate} />
    </>
  );
}
