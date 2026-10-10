"use client";
import { useState } from "react";
import { put, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Notice, Skeleton, roleLabel, useAction } from "@/components/ui";
import { Back, Check } from "@/components/kit";

const ROLES = [
  "audit_engineer",
  "solution_architect",
  "technical_lead",
  "sales_manager",
  "sales_head",
  "project_manager",
  "director",
] as const;

function GateRow({ g, canEdit, onSaved }: { g: S["GateConfigOut"]; canEdit: boolean; onSaved: () => void }) {
  const [roles, setRoles] = useState<string[]>(g.approver_roles);
  const [ack, setAck] = useState(g.requires_customer_ack);
  const { busy, run } = useAction();
  const changed = ack !== g.requires_customer_ack || roles.slice().sort().join() !== g.approver_roles.slice().sort().join();
  return (
    <div className="section stack">
      <div className="row between">
        <h2>{g.label}</h2>
        {canEdit && changed && (
          <button
            className="btn primary small"
            disabled={busy || roles.length === 0}
            onClick={async () => {
              const r = await run(
                () =>
                  put(`/gates/${g.stage}`, {
                    version: g.version,
                    approver_roles: roles,
                    requires_artifact: g.requires_artifact,
                    requires_customer_ack: ack,
                  }),
                "Saved",
              );
              if (r !== undefined) onSaved();
            }}
          >
            Save
          </button>
        )}
      </div>
      <p className="muted small">
        Approved by any one of the roles below, never by the person who submitted the stage.
        {g.artifact_type ? ` Locks the ${g.artifact_type.replace(/_/g, " ")}.` : ""}
      </p>
      <div className="row" role="group" aria-label={`Who approves ${g.label}`}>
        {ROLES.map((r) => (
          <Check
            key={r}
            checked={roles.includes(r)}
            onChange={(v) => canEdit && setRoles(v ? [...roles, r] : roles.filter((x) => x !== r))}
          >
            {roleLabel(r)}
          </Check>
        ))}
      </div>
      <Check checked={ack} onChange={(v) => canEdit && setAck(v)}>
        The customer acknowledges this stage before it is approved
      </Check>
      {roles.length === 0 && <p className="small muted">Choose at least one role.</p>}
    </div>
  );
}

/** Who approves each of the eight stages. */
export default function Gates() {
  const { can } = useMe();
  const gates = useData<S["GateConfigOut"][]>("/gates");
  const canEdit = can("gate:configure");
  return (
    <div>
      <Back href="/settings" label="Settings" />
      <div className="page-head">
        <div>
          <h1>Stage approvals</h1>
          <p>Each stage ends with an approval. The next stage cannot open until it is recorded.</p>
        </div>
      </div>
      {!canEdit && <Notice>You can see these settings. An Admin or the Director changes them.</Notice>}
      {gates.error && <Notice tone="bad">{gates.error}</Notice>}
      {!gates.data ? (
        <Skeleton lines={8} />
      ) : (
        gates.data.map((g) => <GateRow key={`${g.stage}-${g.version}`} g={g} canEdit={canEdit} onSaved={() => void gates.reload()} />)
      )}
    </div>
  );
}
