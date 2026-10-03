"use client";
import { useState } from "react";
import { ApiError, patch, post, type S } from "@/lib/api";
import { useData, useMe, useToast } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, roleLabel, useAction } from "@/components/ui";
import { Drawer, toList } from "@/components/kit";

type Gap = S["GapOut"];
type Register = S["RegisterDetailOut"];

function Affected({ items }: { items: string[] }) {
  if (!items.length) return null;
  const shown = items.slice(0, 3);
  return (
    <div className="chips" style={{ marginTop: 4 }}>
      {shown.map((a) => (
        <Badge key={a}>{a.length > 34 ? a.slice(0, 32) + "..." : a}</Badge>
      ))}
      {items.length > 3 && <Badge>+{items.length - 3} more</Badge>}
    </div>
  );
}

function EditGap({ pid, rid, gap, onClose, onDone }: { pid: string; rid: string; gap: Gap; onClose: () => void; onDone: () => void }) {
  const { busy, run } = useAction();
  const [f, setF] = useState({
    title: gap.title.replace(/^Verify on site: /, ""),
    priority: gap.priority,
    status: gap.status === "verify" ? "open" : gap.status,
    qty: gap.qty_hint?.toString() ?? "",
    affected: gap.affected.join("\n"),
    recommendation: gap.recommendation ?? "",
    reason: "",
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });
  async function save() {
    const r = await run(
      () =>
        patch(`/projects/${pid}/gaps/${rid}/items/${gap.id}`, {
          version: gap.version,
          reason: f.reason,
          title: f.title,
          priority: f.priority,
          status: f.status,
          qty_hint: f.qty === "" ? null : Number(f.qty),
          affected: toList(f.affected),
          recommendation: f.recommendation,
        }),
      "Gap updated",
    );
    if (r !== undefined) onDone();
  }
  return (
    <Drawer title={`${gap.code}`} onClose={onClose}>
      <Field id="gt" label="Title">
        <input id="gt" type="text" value={f.title} onChange={set("title")} />
      </Field>
      <div className="grid2">
        <Field id="gp" label="Priority">
          <select id="gp" value={f.priority} onChange={set("priority")}>
            <option value="high">High priority</option>
            <option value="consider">To consider</option>
          </select>
        </Field>
        <Field id="gs" label="Status" hint="Dismiss a gap the customer does not need.">
          <select id="gs" value={f.status} onChange={set("status")}>
            <option value="open">Open</option>
            <option value="accepted">Accepted by the customer</option>
            <option value="disputed">Disputed</option>
            <option value="dismissed">Dismissed</option>
          </select>
        </Field>
      </div>
      <Field id="gq" label="How many" hint="Drives the quantity on the BOQ for per-gap lines.">
        <input id="gq" type="number" min={0} value={f.qty} onChange={set("qty")} />
      </Field>
      <Field id="ga" label="Affected assets" hint="One per line.">
        <textarea id="ga" value={f.affected} onChange={set("affected")} />
      </Field>
      <Field id="gr" label="Recommendation">
        <textarea id="gr" value={f.recommendation} onChange={set("recommendation")} />
      </Field>
      <Field id="why" label="Reason for this change" hint="Kept with your name in the history.">
        <input id="why" type="text" value={f.reason} onChange={set("reason")} />
      </Field>
      <div className="row">
        <button className="btn primary" disabled={busy || f.reason.trim().length < 3} onClick={save}>
          Save
        </button>
        <button className="btn quiet" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Drawer>
  );
}

function AddGap({ pid, rid, onClose, onDone }: { pid: string; rid: string; onClose: () => void; onDone: () => void }) {
  const { busy, run } = useAction();
  const [f, setF] = useState({ title: "", component: "general", lens: "security", priority: "consider", gap_type: "", recommendation: "", reason: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });
  async function save() {
    const r = await run(
      () => post(`/projects/${pid}/gaps/${rid}/items`, { ...f, gap_type: f.gap_type || f.title.toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 50) || "manual_gap" }),
      "Gap added",
    );
    if (r !== undefined) onDone();
  }
  return (
    <Drawer title="Add a gap by hand" onClose={onClose}>
      <p className="stepnote">For something the audit cannot see, such as what you noticed during the walkthrough.</p>
      <Field id="nt" label="Title">
        <input id="nt" type="text" value={f.title} onChange={set("title")} />
      </Field>
      <div className="grid3">
        <Field id="nc" label="Component">
          <select id="nc" value={f.component} onChange={set("component")}>
            {["endpoint", "server", "firewall", "nas", "switch", "router", "access_point", "general"].map((c) => (
              <option key={c} value={c}>
                {roleLabel(c)}
              </option>
            ))}
          </select>
        </Field>
        <Field id="nl" label="Lens">
          <select id="nl" value={f.lens} onChange={set("lens")}>
            {["security", "resilience", "productivity", "health"].map((c) => (
              <option key={c} value={c}>
                {roleLabel(c)}
              </option>
            ))}
          </select>
        </Field>
        <Field id="np" label="Priority">
          <select id="np" value={f.priority} onChange={set("priority")}>
            <option value="high">High priority</option>
            <option value="consider">To consider</option>
          </select>
        </Field>
      </div>
      <Field id="nr" label="Recommendation">
        <textarea id="nr" value={f.recommendation} onChange={set("recommendation")} />
      </Field>
      <Field id="nw" label="Reason" hint="Why you are adding it.">
        <input id="nw" type="text" value={f.reason} onChange={set("reason")} />
      </Field>
      <div className="row">
        <button className="btn primary" disabled={busy || f.title.trim().length < 3 || f.reason.trim().length < 3} onClick={save}>
          Add gap
        </button>
        <button className="btn quiet" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Drawer>
  );
}

export function GapsTab({ projectId }: { projectId: string }) {
  const { can } = useMe();
  const toast = useToast();
  const reg = useData<Register>(can("infra:read") ? `/projects/${projectId}/gaps` : null);
  const { busy, run } = useAction();
  const [editing, setEditing] = useState<Gap | null>(null);
  const [adding, setAdding] = useState(false);
  const canWrite = can("infra:write");
  if (!can("infra:read")) return <Notice tone="warn">You do not have access to the gap register.</Notice>;
  if (reg.loading && !reg.data && !reg.error) return <Skeleton lines={6} />;

  async function generate() {
    try {
      await run(() => post(`/projects/${projectId}/gaps`), "Gap register drafted from the audit");
    } catch (e) {
      if (e instanceof ApiError) toast(e.message, true);
    }
    reg.reload();
  }

  const r = reg.data;
  if (!r) {
    return (
      <Empty
        title="No gap register yet"
        action={
          canWrite ? (
            <button className="btn primary" disabled={busy} onClick={generate}>
              Draft from the audit
            </button>
          ) : undefined
        }
      >
        The rules compare the locked current infrastructure with the target and list every difference, in priority order.
      </Empty>
    );
  }
  const draft = r.status === "draft";
  const by = (pred: (g: Gap) => boolean) => r.gaps.filter(pred);
  const high = by((g) => g.priority === "high" && ["open", "accepted", "disputed"].includes(g.status));
  const consider = by((g) => g.priority === "consider" && ["open", "accepted", "disputed"].includes(g.status));
  const verify = by((g) => g.status === "verify");
  const dismissed = by((g) => g.status === "dismissed");

  const Row = ({ g }: { g: Gap }) => (
    <div className={`gap ${g.status}`}>
      <div className="code">{g.code}</div>
      <div>
        <div className="t">{g.title}</div>
        <div className="muted small">
          {roleLabel(g.component)}, {g.lens}
          {g.qty_hint ? <> , <span className="num">{g.qty_hint}</span> affected</> : null}
          {g.source === "manual" ? <> , added by hand</> : null}
        </div>
        <Affected items={g.affected} />
        {g.recommendation && <div className="small" style={{ marginTop: 6, maxWidth: "68ch" }}>{g.recommendation}</div>}
        {g.last_change_reason && <div className="muted small" style={{ marginTop: 4 }}>Last change: {g.last_change_reason}</div>}
      </div>
      <div className="row" style={{ alignSelf: "start" }}>
        {g.status === "disputed" && <Badge tone="warn">Disputed</Badge>}
        {g.status === "accepted" && <Badge tone="ok">Accepted</Badge>}
        {draft && canWrite && (
          <button className="btn small" onClick={() => setEditing(g)}>
            {g.status === "verify" ? "Decide" : "Edit"}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <>
      <div className="row between" style={{ marginBottom: 12 }}>
        <div>
          <h2>
            Gap register v{r.number} <Badge tone={draft ? "warn" : "ok"}>{draft ? "Draft" : "Locked"}</Badge>
          </h2>
          <p className="stepnote">
            {high.length} high priority, {consider.length} to consider{verify.length ? `, ${verify.length} to verify on site` : ""}. Rules
            propose, people decide: change anything, with a reason.
          </p>
        </div>
        <div className="row">
          {draft && canWrite && (
            <>
              <button className="btn" onClick={() => setAdding(true)}>
                Add a gap
              </button>
              <button
                className="btn primary"
                disabled={busy || verify.length > 0}
                title={verify.length ? "Decide every verify-on-site item first" : undefined}
                onClick={async () => {
                  await run(() => post(`/projects/${projectId}/gaps/${r.id}/lock`, undefined, { idem: true }), "Gap register locked");
                  reg.reload();
                }}
              >
                Lock register
              </button>
            </>
          )}
          {!draft && canWrite && (
            <button className="btn" disabled={busy} onClick={generate}>
              Draft a new version
            </button>
          )}
        </div>
      </div>

      {verify.length > 0 && (
        <div className="section">
          <h3>Verify on site</h3>
          <p className="stepnote">The audit left these blank. Turn each into a gap, or dismiss it with a reason, before locking.</p>
          {verify.map((g) => (
            <Row key={g.id} g={g} />
          ))}
        </div>
      )}
      <div className="section">
        <h3>High priority</h3>
        {high.length === 0 ? <p className="muted">None.</p> : high.map((g) => <Row key={g.id} g={g} />)}
      </div>
      <div className="section">
        <h3>To consider</h3>
        {consider.length === 0 ? <p className="muted">None.</p> : consider.map((g) => <Row key={g.id} g={g} />)}
      </div>
      {dismissed.length > 0 && (
        <div className="section">
          <h3>Dismissed</h3>
          {dismissed.map((g) => (
            <Row key={g.id} g={g} />
          ))}
        </div>
      )}

      {editing && (
        <EditGap
          pid={projectId}
          rid={r.id}
          gap={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            reg.reload();
          }}
        />
      )}
      {adding && (
        <AddGap
          pid={projectId}
          rid={r.id}
          onClose={() => setAdding(false)}
          onDone={() => {
            setAdding(false);
            reg.reload();
          }}
        />
      )}
    </>
  );
}
