"use client";
import { useEffect, useState } from "react";
import { get, put } from "@/lib/api";
import { useMe, useToast } from "@/lib/hooks";
import { Field, Notice, Skeleton, useAction } from "@/components/ui";
import { Back, toList } from "@/components/kit";

type Company = Record<string, unknown>;
type Record_ = { data: Company; version: number | null };

const str = (v: unknown) => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));
const lines = (v: unknown) => (Array.isArray(v) ? v.map(String).join("\n") : "");

/** Letterhead, terms, quote numbers, price validity and the minimum margin (ADR 0028). */
export default function CompanySettings() {
  const { can } = useMe();
  const toast = useToast();
  const [rec, setRec] = useState<Record_ | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [f, setF] = useState<Record<string, string>>({});
  const { busy, run } = useAction();

  async function load() {
    try {
      const r = await get<Record_>("/boq/company/record");
      setRec(r);
      const d = r.data;
      setF({
        legal_name: str(d.legal_name),
        brand: str(d.brand),
        tagline: str(d.tagline),
        address_lines: lines(d.address_lines),
        phones: lines(d.phones),
        email: str(d.email),
        gstin: str(d.gstin),
        quote_prefix: str(d.quote_prefix),
        default_validity_days: str(d.default_validity_days),
        min_margin_pct: str(d.min_margin_pct),
        signatory_name: str(d.signatory_name),
        signatory_designation: str(d.signatory_designation),
        intro: str(d.intro),
        terms: lines(d.terms),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the settings.");
    }
  }
  useEffect(() => {
    void load();
  }, []);

  if (!can("settings:edit")) return <Notice tone="warn">Only an Admin or the Director changes company settings.</Notice>;
  if (error) return <Notice tone="bad">{error}</Notice>;
  if (!rec) return <Skeleton lines={10} />;
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const margin = Number(f.min_margin_pct);
  const validity = Number(f.default_validity_days);
  const badMargin = !(f.min_margin_pct !== "" && margin >= 0 && margin <= 90);
  const badValidity = !(Number.isInteger(validity) && validity >= 1 && validity <= 365);
  const badPrefix = !/^[A-Za-z0-9-]{1,20}$/.test(f.quote_prefix ?? "");

  return (
    <div>
      <Back href="/settings" label="Settings" />
      <div className="page-head">
        <div>
          <h1>Company and quotation</h1>
          <p>What every quotation, plan and certificate prints, and the money rules behind them.</p>
        </div>
      </div>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const data = {
            ...rec.data,
            legal_name: f.legal_name.trim(),
            brand: f.brand.trim(),
            tagline: f.tagline.trim(),
            // address lines carry commas, so only new lines separate them
            address_lines: f.address_lines
              .split("\n")
              .map((x) => x.trim())
              .filter(Boolean),
            phones: toList(f.phones),
            email: f.email.trim(),
            gstin: f.gstin.trim().toUpperCase(),
            quote_prefix: f.quote_prefix.trim(),
            default_validity_days: validity,
            min_margin_pct: margin,
            signatory_name: f.signatory_name.trim(),
            signatory_designation: f.signatory_designation.trim(),
            intro: f.intro.trim(),
            terms: f.terms
              .split("\n")
              .map((t) => t.trim())
              .filter(Boolean),
          };
          const r = await run(() => put("/boq/company", { data, version: rec.version }));
          if (r !== undefined) {
            toast("Saved. New quotations use these settings; issued ones keep the PDF they were sent with.");
            void load();
          }
        }}
      >
        <div className="section stack">
          <h2>Letterhead</h2>
          <div className="form-grid">
            <Field id="co-legal" label="Legal name">
              <input id="co-legal" value={f.legal_name} onChange={set("legal_name")} />
            </Field>
            <Field id="co-brand" label="Brand on the letterhead">
              <input id="co-brand" value={f.brand} onChange={set("brand")} />
            </Field>
            <Field id="co-gstin" label="GSTIN">
              <input id="co-gstin" value={f.gstin} maxLength={15} onChange={set("gstin")} />
            </Field>
            <Field id="co-email" label="Email">
              <input id="co-email" type="email" value={f.email} onChange={set("email")} />
            </Field>
            <div className="wide">
              <Field id="co-tag" label="Tagline">
                <input id="co-tag" value={f.tagline} onChange={set("tagline")} />
              </Field>
            </div>
            <Field id="co-addr" label="Address" hint="One line per row.">
              <textarea id="co-addr" rows={3} value={f.address_lines} onChange={set("address_lines")} />
            </Field>
            <Field id="co-phones" label="Phone numbers" hint="One per row.">
              <textarea id="co-phones" rows={3} value={f.phones} onChange={set("phones")} />
            </Field>
          </div>
        </div>
        <div className="section stack">
          <h2>Quotation rules</h2>
          <div className="form-grid">
            <Field
              id="co-prefix"
              label="Quote number prefix"
              hint={`Numbers look like ${f.quote_prefix || "ITCraft"}/AK/2627/030.`}
              error={badPrefix ? "1 to 20 letters, digits or dashes." : undefined}
            >
              <input id="co-prefix" value={f.quote_prefix} onChange={set("quote_prefix")} />
            </Field>
            <Field
              id="co-valid"
              label="Prices valid for (days)"
              hint="Printed in the terms. The owner is told the day before a quote lapses."
              error={badValidity ? "1 to 365 days." : undefined}
            >
              <input id="co-valid" inputMode="numeric" value={f.default_validity_days} onChange={set("default_validity_days")} />
            </Field>
            <Field
              id="co-margin"
              label="Minimum margin (percent)"
              hint="Lines under it must be accepted one by one, with a reason, by whoever approves the pricing."
              error={badMargin ? "0 to 90 percent." : undefined}
            >
              <input id="co-margin" inputMode="decimal" value={f.min_margin_pct} onChange={set("min_margin_pct")} />
            </Field>
          </div>
        </div>
        <div className="section stack">
          <h2>Wording and signature</h2>
          <div className="form-grid">
            <Field id="co-sig" label="Signed by">
              <input id="co-sig" value={f.signatory_name} onChange={set("signatory_name")} />
            </Field>
            <Field id="co-sigd" label="Designation">
              <input id="co-sigd" value={f.signatory_designation} onChange={set("signatory_designation")} />
            </Field>
            <div className="wide">
              <Field id="co-intro" label="Opening line" hint="{scope} is replaced with what the quote covers.">
                <input id="co-intro" value={f.intro} onChange={set("intro")} />
              </Field>
            </div>
            <div className="wide">
              <Field id="co-terms" label="Terms" hint="One term per row. {validity} is replaced with the number of days.">
                <textarea id="co-terms" rows={9} value={f.terms} onChange={set("terms")} />
              </Field>
            </div>
          </div>
        </div>
        <div>
          <button className="btn primary" disabled={busy || badMargin || badValidity || badPrefix}>
            Save settings
          </button>
        </div>
      </form>
    </div>
  );
}
