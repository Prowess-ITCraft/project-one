"use client";
import { useState } from "react";
import type { S } from "@/lib/api";
import { message } from "@/lib/api";
import { useToast } from "@/lib/hooks";

export function Badge({
  tone,
  children,
}: {
  tone?: "ok" | "warn" | "bad" | "accent";
  children: React.ReactNode;
}) {
  return <span className={`badge${tone ? ` ${tone}` : ""}`}>{children}</span>;
}

export function Field({
  label,
  hint,
  error,
  children,
  id,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  id: string;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && (
        <span className="err" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function Notice({
  tone,
  children,
}: {
  tone?: "bad" | "warn" | "ok";
  children: React.ReactNode;
}) {
  return (
    <div className={`notice${tone ? ` ${tone}` : ""}`} role={tone === "bad" ? "alert" : undefined}>
      {children}
    </div>
  );
}

export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skel" style={{ width: `${92 - ((i * 13) % 40)}%` }} />
      ))}
    </div>
  );
}

/** Wraps an async action: disables the button while it runs and toasts the outcome. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function run<T>(fn: () => Promise<T>, done?: string): Promise<T | undefined> {
    setBusy(true);
    try {
      const r = await fn();
      if (done) toast(done);
      return r;
    } catch (e) {
      toast(message(e), true);
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { busy, run };
}

const STAGE_SHORT: Record<string, string> = {
  audit_intake: "Audit intake",
  current_infra: "Current IT",
  ideal_infra: "Ideal IT",
  gap_analysis: "Gap analysis",
  boq: "BOQ",
  implementation_plan: "Plan",
  field_work: "Field work",
  completion: "Completion",
};
export const stageName = (s: string) => STAGE_SHORT[s] ?? s;

/** Eight stages on one line: where is this project, and what comes next. */
export function StageRail({ stages }: { stages: S["StageStatusOut"][] }) {
  return (
    <ol className="rail" aria-label="Project stages">
      {stages.map((s, i) => (
        <li
          key={s.stage}
          data-state={s.state}
          aria-current={s.state === "current" ? "step" : undefined}
          style={{ "--i": i } as React.CSSProperties}
        >
          <span className="name">
            {stageName(s.stage)}
            <span className="muted small" style={{ display: "block" }}>
              {s.state === "done"
                ? "Approved"
                : s.state === "current"
                  ? s.pending_submission
                    ? "Waiting for approval"
                    : "In progress"
                  : "Locked"}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** The current stage as a headline: the answer to "where is this project". */
export function StageHero({ stages }: { stages: S["StageStatusOut"][] }) {
  const i = stages.findIndex((s) => s.state === "current");
  if (i < 0) {
    return (
      <div className="stagehero">
        <span className="now">All stages approved</span>
      </div>
    );
  }
  const cur = stages[i];
  return (
    <div className="stagehero">
      <span className="now">{cur.label}</span>
      <span className="of">
        Stage {i + 1} of {stages.length}
        {cur.pending_submission ? ", waiting for approval" : ""}
      </span>
    </div>
  );
}

export const roleLabel = (r: string) => r.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export const priceTone = (s: string) => (s === "valid" ? "ok" : s === "expiring" ? "warn" : "bad");
export const priceWords = (s: string, days: number | null | undefined) =>
  s === "valid"
    ? "Valid"
    : s === "expiring"
      ? days === 0
        ? "Expires today"
        : `Expires in ${days} day${days === 1 ? "" : "s"}`
      : s === "expired"
        ? "Expired"
        : "No price";

