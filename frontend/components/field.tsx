"use client";
import type { S } from "@/lib/api";

/** The ITCraft shield from itcraft.net.in. The wordmark is drawn separately in its colours. */
export function Logo({ size = 28 }: { size?: number }) {
  return <img src="/brand/itcraft-logo-icon.svg" alt="" width={size} height={Math.round(size * 0.87)} className="logo" />;
}

/** ITCRAFT as on the logo and the website: green IT, blue CRAFT. */
export function Wordmark() {
  return (
    <span className="wordmark" aria-label="ITCraft">
      <span className="it">IT</span>
      <span className="craft">CRAFT</span>
    </span>
  );
}

export const FLOW = [
  "assigned",
  "accepted",
  "checked_in",
  "prechecks_done",
  "configured",
  "evidence_uploaded",
  "engine_check",
  "verifier_review",
  "closed",
] as const;

/** Short names for the stations; the full sentence comes from the API's `next_action`. */
export const STATE_SHORT: Record<string, string> = {
  assigned: "Assigned",
  accepted: "Accepted",
  checked_in: "Checked in",
  prechecks_done: "Prechecks",
  configured: "Configured",
  evidence_uploaded: "Evidence",
  engine_check: "Checked",
  verifier_review: "Handed over",
  closed: "Closed",
  blocked: "Blocked",
};

export function stateTone(s: string): "ok" | "warn" | "bad" | "accent" | undefined {
  if (s === "closed") return "ok";
  if (s === "blocked") return "bad";
  if (s === "verifier_review" || s === "engine_check") return "accent";
  if (s === "assigned") return "warn";
  return undefined;
}

/**
 * Nine stations on one circuit trace. Passed stations are filled with trace green, the current
 * one is ringed in ITCraft blue. When work was sent back, a loop is drawn from the hand over
 * back to "configured" with the count, so rework is never hidden.
 */
export function TaskTimeline({ run }: { run: Pick<S["RunOut"], "state" | "blocked_from" | "rework_count"> }) {
  const at = run.state === "blocked" ? (run.blocked_from ?? "assigned") : run.state;
  const cur = FLOW.indexOf(at as (typeof FLOW)[number]);
  const back = run.rework_count > 0;
  return (
    <div className="timeline" data-blocked={run.state === "blocked" || undefined}>
      {back && (
        <svg className="loop" viewBox="0 0 900 34" preserveAspectRatio="none" aria-hidden="true">
          <path d="M 750 32 C 735 4, 465 4, 450 32" />
          <path className="head" d="M 450 32 l -6 -9 M 450 32 l 9 -5" />
        </svg>
      )}
      {back && (
        <span className="loop-label">
          Sent back {run.rework_count} time{run.rework_count === 1 ? "" : "s"}
        </span>
      )}
      <ol aria-label="Task progress">
        {FLOW.map((s, i) => (
          <li
            key={s}
            data-state={i < cur ? "done" : i === cur ? (run.state === "blocked" ? "blocked" : "current") : "todo"}
            aria-current={i === cur ? "step" : undefined}
          >
            <span className="name">{i === cur && run.state === "blocked" ? "Blocked" : STATE_SHORT[s]}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Counts per state placed on the same trace: the Director's view of field work. */
export function StateTrace({ counts, total }: { counts: Record<string, number>; total: number }) {
  return (
    <div className="timeline counts">
      <ol aria-label="Tasks by state">
        {FLOW.map((s) => (
          <li key={s} data-state={counts[s] ? (s === "closed" ? "done" : "current") : "todo"}>
            <span className="count num">{counts[s] ?? 0}</span>
            <span className="name">{STATE_SHORT[s]}</span>
          </li>
        ))}
      </ol>
      <p className="muted small">
        {total} task{total === 1 ? "" : "s"}
        {counts.blocked ? `, ${counts.blocked} blocked` : ""}
      </p>
    </div>
  );
}
