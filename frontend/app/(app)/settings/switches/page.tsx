"use client";
import { put, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Notice, Skeleton, useAction } from "@/components/ui";
import { Back } from "@/components/kit";

const ABOUT: Record<string, { title: string; text: string }> = {
  field_customer_codes: {
    title: "Customer codes at check-in and hand over",
    text: "The customer reads a one-time code from their email to the engineer. Off for now (ADR 0025); the arrival photo and its location still apply.",
  },
  ml_enabled: {
    title: "Learning",
    text: "Records examples, runs models in shadow mode, suggests BOQ lines from an approved model and warns about unusual prices. Off stops all of it; nothing else changes.",
  },
  customer_portal_login: {
    title: "Customer sign-in",
    text: "Customer representatives sign in with a password. Off: customers use the links and codes sent to them.",
  },
  prismsuite_json_import: {
    title: "PrismSuite JSON reports",
    text: "Accept audit reports exported as JSON as well as Word documents.",
  },
};

/** Feature switches. Each change is recorded in the audit log and takes effect within 30 seconds. */
export default function Switches() {
  const { can } = useMe();
  const flags = useData<S["FlagOut"][]>("/admin/feature-flags");
  const { busy, run } = useAction();
  if (!can("flags:manage")) return <Notice tone="warn">Only an Admin or the Director changes these switches.</Notice>;
  return (
    <div>
      <Back href="/settings" label="Settings" />
      <div className="page-head">
        <div>
          <h1>Switches</h1>
          <p>Turn parts of Project One on or off. A change reaches every server within 30 seconds.</p>
        </div>
      </div>
      {flags.error && <Notice tone="bad">{flags.error}</Notice>}
      {!flags.data ? (
        <Skeleton lines={5} />
      ) : (
        flags.data.map((f) => {
          const about = ABOUT[f.key] ?? { title: f.key.replace(/_/g, " "), text: "" };
          return (
            <div key={f.key} className="section row between">
              <div className="stack" style={{ maxWidth: "60ch" }}>
                <strong>
                  {about.title} <Badge tone={f.enabled ? "ok" : undefined}>{f.enabled ? "On" : "Off"}</Badge>
                </strong>
                <span className="muted small">{about.text}</span>
                {f.enabled !== f.default && <span className="small">Changed from the default ({f.default ? "on" : "off"}).</span>}
              </div>
              <button
                className={`btn${f.enabled ? "" : " primary"}`}
                disabled={busy}
                onClick={async () => {
                  await run(() => put(`/admin/feature-flags/${f.key}`, { enabled: !f.enabled }), f.enabled ? "Switched off" : "Switched on");
                  void flags.reload();
                }}
              >
                {f.enabled ? "Switch off" : "Switch on"}
              </button>
            </div>
          );
        })
      )}
    </div>
  );
}
