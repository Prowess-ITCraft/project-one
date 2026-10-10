"use client";
import { useState } from "react";
import type { S } from "@/lib/api";
import { Field, useAction } from "@/components/ui";

const SEGMENTS = ["micro", "small", "medium", "large"] as const;

export function CustomerForm({
  edit = false,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: Partial<S["CustomerOut"]> & { address_line1?: string; address_line2?: string | null };
  submitLabel: string;
  onSubmit: (body: Record<string, unknown>) => Promise<unknown>;
  onCancel?: () => void;
  /** Editing: the address lines are set when the customer is created and are not changed here. */
  edit?: boolean;
}) {
  const [f, setF] = useState({
    legal_name: initial?.legal_name ?? "",
    display_name: initial?.display_name ?? "",
    gstin: initial?.gstin ?? "",
    segment: (initial?.segment as (typeof SEGMENTS)[number]) ?? "small",
    industry: initial?.industry ?? "",
    employee_count: initial?.employee_count ? String(initial.employee_count) : "",
    address_line1: initial?.address_line1 ?? "",
    address_line2: initial?.address_line2 ?? "",
    city: initial?.city ?? "",
    state: initial?.state ?? "",
    pincode: initial?.pincode ?? "",
    notes: initial?.notes ?? "",
  });
  const { busy, run } = useAction();
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });
  const pinOk = /^\d{6}$/.test(f.pincode);
  return (
    <form
      className="section stack"
      onSubmit={async (e) => {
        e.preventDefault();
        await run(() =>
          onSubmit({
            legal_name: f.legal_name.trim(),
            display_name: f.display_name.trim() || null,
            gstin: f.gstin.trim().toUpperCase() || null,
            segment: f.segment,
            industry: f.industry.trim() || null,
            employee_count: f.employee_count ? Number(f.employee_count) : null,
            ...(edit ? {} : { address_line1: f.address_line1.trim(), address_line2: f.address_line2.trim() || null }),
            city: f.city.trim(),
            state: f.state.trim(),
            pincode: f.pincode.trim(),
            notes: f.notes.trim() || null,
          }),
        );
      }}
    >
      <div className="form-grid">
        <Field id="c-legal" label="Legal name">
          <input id="c-legal" required value={f.legal_name} onChange={set("legal_name")} />
        </Field>
        <Field id="c-display" label="Short name" hint="How people say it. Leave empty to use the legal name.">
          <input id="c-display" value={f.display_name} onChange={set("display_name")} />
        </Field>
        <Field id="c-gstin" label="GSTIN" hint="15 characters, if they have one.">
          <input id="c-gstin" value={f.gstin} maxLength={15} onChange={set("gstin")} />
        </Field>
        <Field id="c-seg" label="Size">
          <select id="c-seg" value={f.segment} onChange={set("segment")}>
            {SEGMENTS.map((s) => (
              <option key={s} value={s}>
                {s[0].toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </Field>
        <Field id="c-ind" label="Industry">
          <input id="c-ind" value={f.industry} onChange={set("industry")} />
        </Field>
        <Field id="c-emp" label="Employees">
          <input id="c-emp" inputMode="numeric" value={f.employee_count} onChange={set("employee_count")} />
        </Field>
        {!edit && (
          <>
            <Field id="c-a1" label="Address">
              <input id="c-a1" required value={f.address_line1} onChange={set("address_line1")} />
            </Field>
            <Field id="c-a2" label="Address, second line">
              <input id="c-a2" value={f.address_line2} onChange={set("address_line2")} />
            </Field>
          </>
        )}
        <Field id="c-city" label="City">
          <input id="c-city" required value={f.city} onChange={set("city")} />
        </Field>
        <Field id="c-state" label="State">
          <input id="c-state" required value={f.state} onChange={set("state")} />
        </Field>
        <Field id="c-pin" label="PIN code" error={f.pincode && !pinOk ? "Six digits." : undefined}>
          <input id="c-pin" required inputMode="numeric" maxLength={6} value={f.pincode} onChange={set("pincode")} />
        </Field>
        <div className="wide">
          <Field id="c-notes" label="Notes">
            <textarea id="c-notes" rows={2} value={f.notes} onChange={set("notes")} />
          </Field>
        </div>
      </div>
      <div className="row">
        <button className="btn primary" disabled={busy || !f.legal_name || (!edit && !f.address_line1) || !f.city || !f.state || !pinOk}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="btn quiet" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

