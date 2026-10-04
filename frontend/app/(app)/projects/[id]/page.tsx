"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Back, Tabs } from "@/components/kit";
import { IntakeTab } from "@/components/project/IntakeTab";
import { InfraTab } from "@/components/project/InfraTab";
import { GapsTab } from "@/components/project/GapsTab";
import { BoqTab } from "@/components/project/BoqTab";
import { EstimateReadiness } from "@/components/project/EstimatePanel";
import { PlanTab } from "@/components/project/PlanTab";
import { FieldTab } from "@/components/project/FieldTab";
import { CompletionTab } from "@/components/project/CompletionTab";
import { dateTime, del, post, put, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import {
  Badge,
  Field,
  Notice,
  Skeleton,
  StageRail,
  roleLabel,
  stageName,
  useAction,
} from "@/components/ui";

const TAB_IDS = ["overview", "audit", "brief", "infra", "gaps", "boq", "plan", "field", "completion"] as const;
type TabId = (typeof TAB_IDS)[number];

const STAGE_HELP: Record<string, string> = {
  audit_intake: "Upload the PrismSuite report, review what was read, and approve it. That locks the audit for this stage.",
  current_infra: "Open the Infrastructure tab, build the current state from the approved audit, and lock it.",
  ideal_infra: "Fill in the Questionnaire, then build and lock the ideal state from the Infrastructure tab.",
  gap_analysis: "Open the Gaps tab, review and decide every item, and lock the register.",
  boq: "Open the BOQ tab, draft it, enter prices, get pricing approved, issue and record the customer PO.",
  implementation_plan: "Open the Plan tab: draft the plan, add the customer's downtime windows, schedule it and lock it.",
  field_work: "Open the Field work tab and start it. Engineers work through each task; a verifier closes it. When it is all done, lock the field work summary on the Completion tab.",
  completion: "Open the Completion tab: get the rescan approved, lock the completion report, then submit it here for the customer and the Director.",
};

/** A single-use link for one of the customer's sign-off contacts. Staff send it themselves. */
function AckLink({ projectId, customerId, submissionId }: { projectId: string; customerId: string; submissionId: string }) {
  const contacts = useData<S["ContactOut"][]>(`/customers/${customerId}/contacts`);
  const { busy, run } = useAction();
  const [contact, setContact] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const signers = (contacts.data ?? []).filter((c) => c.can_sign_off && c.email);
  const chosen = contact || signers[0]?.id || "";
  if (contacts.data && signers.length === 0) {
    return <p className="muted small">Add a contact who can sign off, with an email address, to the customer first.</p>;
  }
  return (
    <div className="stack" style={{ marginTop: 10, maxWidth: 520 }}>
      <div className="row">
        <select aria-label="Customer contact" value={chosen} onChange={(e) => setContact(e.target.value)} style={{ maxWidth: 260 }}>
          {signers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.full_name}
            </option>
          ))}
        </select>
        <button
          className="btn small"
          disabled={busy || !chosen}
          onClick={async () => {
            const r = await run(() =>
              post<S["AckIssueOut"]>(`/projects/${projectId}/submissions/${submissionId}/customer-ack`, { contact_id: chosen }),
            );
            if (r) setUrl(r.url);
          }}
        >
          Get a link for the customer
        </button>
      </div>
      {url && (
        <div className="row">
          <input readOnly value={url} aria-label="Acknowledgement link" onFocus={(e) => e.currentTarget.select()} />
          <button className="btn quiet small" onClick={() => navigator.clipboard?.writeText(url)}>
            Copy
          </button>
        </div>
      )}
    </div>
  );
}

function GatePanel({
  projectId,
  tracker,
  artifacts,
  reload,
}: {
  projectId: string;
  tracker: S["ProjectTrackerOut"];
  artifacts: S["ArtifactOut"][];
  reload: () => void;
}) {
  const { can, me } = useMe();
  const { busy, run } = useAction();
  const cur = tracker.stages.find((s) => s.state === "current");
  const [artifact, setArtifact] = useState("");
  const [note, setNote] = useState("");
  const [reject, setReject] = useState(false);
  const [comment, setComment] = useState("");
  if (!cur) {
    return (
      <div className="section">
        <h2>All stages are approved</h2>
        <p className="lede">This project has completed every gate. The completion report and the certificate are on the Completion tab.</p>
        <a className="btn primary" href="#completion">
          Open the report and certificate
        </a>
      </div>
    );
  }
  const options = artifacts.filter((a) => a.stage === cur.stage);
  const chosen = artifact || options[0]?.id || "";
  const sub = cur.pending_submission;

  return (
    <div className="section">
      <div className="row between">
        <h2>{cur.label}</h2>
        {sub && <Badge tone="warn">Waiting for approval</Badge>}
      </div>
      <p className="lede">{STAGE_HELP[cur.stage]}</p>

      {sub ? (
        <div className="stack">
          <dl className="kv">
            <dt>Submitted</dt>
            <dd>{dateTime(sub.created_at)}</dd>
            {sub.note && (
              <>
                <dt>Note</dt>
                <dd>{sub.note}</dd>
              </>
            )}
            {sub.requires_customer_ack && (
              <>
                <dt>Customer</dt>
                <dd>
                  {sub.customer_ack_at ? (
                    <Badge tone="ok">Acknowledged {dateTime(sub.customer_ack_at)}</Badge>
                  ) : (
                    <Badge tone="warn">Acknowledgement needed before approval</Badge>
                  )}
                  {!sub.customer_ack_at && can("customer_ack:issue") && (
                    <AckLink projectId={projectId} customerId={tracker.project.customer_id} submissionId={sub.id} />
                  )}
                </dd>
              </>
            )}
          </dl>
          {sub.submitted_by === me.id && (
            <Notice>You submitted this stage, so someone else has to approve it.</Notice>
          )}
          {can("gate:approve") && sub.submitted_by !== me.id && (
            <>
              {reject ? (
                <div className="stack">
                  <Field id="reason" label="Why is it being sent back?" hint="At least 5 characters. The team sees this.">
                    <textarea id="reason" value={comment} onChange={(e) => setComment(e.target.value)} />
                  </Field>
                  <div className="row">
                    <button
                      className="btn danger"
                      disabled={busy || comment.trim().length < 5}
                      onClick={async () => {
                        await run(
                          () => post(`/projects/${projectId}/submissions/${sub.id}/reject`, { comment }, { idem: true }),
                          "Sent back",
                        );
                        setReject(false);
                        reload();
                      }}
                    >
                      Send back
                    </button>
                    <button className="btn quiet" onClick={() => setReject(false)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="row">
                  <button
                    className="btn primary"
                    disabled={busy}
                    onClick={async () => {
                      await run(
                        () => post(`/projects/${projectId}/submissions/${sub.id}/approve`, {}, { idem: true }),
                        "Stage approved",
                      );
                      reload();
                    }}
                  >
                    Approve stage
                  </button>
                  <button className="btn" onClick={() => setReject(true)}>
                    Send back
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      ) : can("gate:submit") ? (
        options.length === 0 ? (
          <Notice>
            {cur.stage === "audit_intake"
              ? "Nothing is locked for this stage yet. Import the audit report below and approve it first."
              : "Nothing is locked for this stage yet."}
          </Notice>
        ) : (
          <div className="stack" style={{ maxWidth: 520 }}>
            <Field id="art" label="Locked output to approve">
              <select id="art" value={chosen} onChange={(e) => setArtifact(e.target.value)}>
                {options.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.title}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="note" label="Note for the approver" hint="Optional">
              <textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <div>
              <button
                className="btn primary"
                disabled={busy || !chosen}
                onClick={async () => {
                  await run(
                    () =>
                      post(
                        `/projects/${projectId}/stages/${cur.stage}/submit`,
                        { artifact_id: chosen, note: note || null },
                        { idem: true },
                      ),
                    "Submitted for approval",
                  );
                  setNote("");
                  reload();
                }}
              >
                Submit for approval
              </button>
            </div>
          </div>
        )
      ) : (
        <p className="muted">You can follow this stage but not submit it.</p>
      )}
    </div>
  );
}

function AuditSection({ projectId, stage, onEstimate }: { projectId: string; stage: string; onEstimate: () => void }) {
  const { can } = useMe();
  const imports = useData<S["ImportOut"][]>(can("prismsuite:review") ? `/prismsuite/imports/by-project/${projectId}` : null);
  const { busy, run } = useAction();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<"baseline" | "rescan">("baseline");
  const hasBaseline = (imports.data ?? []).some((i) => i.status === "approved" && (i.kind ?? "baseline") === "baseline");

  if (!can("prismsuite:review")) return null;

  async function upload() {
    if (!file) return;
    const r = await run(async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("purpose", "audit_report");
      form.append("project_id", projectId);
      const f = await post<S["FileOut"]>("/files", undefined, { form });
      return post<S["ImportOut"]>("/prismsuite/imports", { project_id: projectId, file_id: f.id, kind }, { idem: true });
    }, kind === "rescan" ? "Rescan imported. Review and approve it like the first report." : "Report imported");
    if (r) {
      setFile(null);
      imports.reload();
    }
  }

  return (
    <div className="section">
      <h2>Audit reports</h2>
      <p className="lede">
        The PrismSuite Word report for this customer. Each import is read field by field, and anything it could not read is listed for review.
      </p>
      {can("prismsuite:import") && (
        <div className="row" style={{ marginBottom: 16 }}>
          {hasBaseline && (
            <select aria-label="Which audit" value={kind} onChange={(e) => setKind(e.target.value as "baseline" | "rescan")} style={{ maxWidth: 260 }}>
              <option value="baseline">Before the work (replaces the audit)</option>
              <option value="rescan">After the work (rescan)</option>
            </select>
          )}
          <input
            aria-label="Audit report file"
            type="file"
            accept=".docx,.json"
            style={{ maxWidth: 340 }}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button className="btn primary" disabled={!file || busy} onClick={upload}>
            {busy ? "Reading report" : "Upload and import"}
          </button>
        </div>
      )}
      {imports.loading && !imports.data && <Skeleton lines={2} />}
      {imports.data && imports.data.length === 0 && (
        <p className="muted">No report has been imported yet{stage === "audit_intake" ? ". Start with the file picker above." : "."}</p>
      )}
      {imports.data && imports.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Revision</th>
              <th>Status</th>
              <th>Fields to check</th>
              <th className="right">Imported</th>
            </tr>
          </thead>
          <tbody>
            {imports.data.map((i) => {
              const counts = (i.read_summary as { counts?: Record<string, number> }).counts ?? {};
              const attention = (counts.conflict ?? 0) + (counts.missing ?? 0) + (counts.unreadable ?? 0);
              return (
                <tr key={i.id}>
                  <td data-label="Revision">
                    <Link href={`/imports/${i.id}`}>Revision {i.revision}</Link>
                    {i.kind === "rescan" && <span className="muted small"> rescan after the work</span>}
                  </td>
                  <td data-label="Status">
                    <Badge tone={i.status === "approved" ? "ok" : i.status === "rejected" ? "bad" : i.status === "in_review" ? "warn" : undefined}>
                      {i.status.replace("_", " ")}
                    </Badge>
                  </td>
                  <td data-label="Fields to check" className="num">
                    {attention}
                  </td>
                  <td data-label="Imported" className="right">
                    {dateTime(i.created_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {stage === "audit_intake" || stage === "current_infra" || stage === "ideal_infra" || stage === "gap_analysis" ? (
        <EstimateReadiness key={imports.data?.length ?? 0} projectId={projectId} onOpen={onEstimate} />
      ) : null}
    </div>
  );
}

function Members({ projectId }: { projectId: string }) {
  const { can } = useMe();
  const members = useData<S["MemberOut"][]>(`/projects/${projectId}/members`);
  const users = useData<{ items: S["UserOut"][] }>(can("user:read") && can("project:manage_members") ? "/users?size=200" : null);
  const { busy, run } = useAction();
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("audit_engineer");
  const canManage = can("project:manage_members");
  const staff = (users.data?.items ?? []).filter((u) => !u.roles.includes("customer_rep") && u.is_active);

  return (
    <div className="section">
      <h2>Team</h2>
      {members.loading && !members.data && <Skeleton lines={2} />}
      {members.data && members.data.length === 0 && <p className="muted">Nobody has been added yet.</p>}
      {members.data && members.data.length > 0 && (
        <table className="table">
          <tbody>
            {members.data.map((m) => (
              <tr key={m.user_id}>
                <td data-label="Name">{m.full_name ?? "System account"}</td>
                <td data-label="Role">{roleLabel(m.project_role)}</td>
                <td className="right">
                  {canManage && (
                    <button
                      className="btn quiet small"
                      disabled={busy}
                      onClick={async () => {
                        await run(() => del(`/projects/${projectId}/members/${m.user_id}`), "Removed from the project");
                        members.reload();
                      }}
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canManage && staff.length > 0 && (
        <div className="row" style={{ marginTop: 14 }}>
          <select aria-label="Person" value={userId} onChange={(e) => setUserId(e.target.value)} style={{ maxWidth: 240 }}>
            <option value="">Choose a person</option>
            {staff.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
          <select aria-label="Project role" value={role} onChange={(e) => setRole(e.target.value)} style={{ maxWidth: 220 }}>
            {["audit_engineer", "solution_architect", "technical_lead", "sales_manager", "sales_head", "project_manager", "field_engineer"].map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
          <button
            className="btn"
            disabled={!userId || busy}
            onClick={async () => {
              await run(() => put(`/projects/${projectId}/members`, { user_id: userId, project_role: role }), "Added to the project");
              setUserId("");
              members.reload();
            }}
          >
            Add to team
          </button>
        </div>
      )}
    </div>
  );
}

export default function Project() {
  const { id } = useParams<{ id: string }>();
  const tracker = useData<S["ProjectTrackerOut"]>(`/projects/${id}/tracker`);
  const artifacts = useData<S["ArtifactOut"][]>(`/projects/${id}/artifacts`);
  const customer = useData<S["CustomerOut"]>(tracker.data ? `/customers/${tracker.data.project.customer_id}` : null);
  const [tab, setTab] = useState<TabId>("overview");
  const [autoEstimate, setAutoEstimate] = useState(false);
  useEffect(() => {
    const read = () => {
      const h = window.location.hash.slice(1) as TabId;
      if (TAB_IDS.includes(h)) setTab(h);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  const go = (t: TabId) => {
    setTab(t);
    if (t !== "boq") setAutoEstimate(false);
    window.history.replaceState(null, "", `#${t}`);
  };
  const openEstimate = () => {
    setAutoEstimate(true);
    setTab("boq");
    window.history.replaceState(null, "", "#boq");
    window.scrollTo({ top: 0 });
  };

  if (tracker.error) return <Notice tone="bad">{tracker.error}</Notice>;
  if (!tracker.data) return <Skeleton lines={8} />;
  const p = tracker.data.project;
  const cur = tracker.data.stages.find((s) => s.state === "current");
  const tabs: { id: TabId; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "audit", label: "Audit intake" },
    { id: "brief", label: "Questionnaire" },
    { id: "infra", label: "Infrastructure" },
    { id: "gaps", label: "Gaps" },
    { id: "boq", label: "BOQ" },
    { id: "plan", label: "Plan" },
    { id: "field", label: "Field work" },
    { id: "completion", label: "Completion" },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <Back href="/projects" label="Projects" />
          <h1>{p.name}</h1>
          <p>
            {customer.data?.display_name ?? ""} <span className="mono muted">{p.code}</span>
          </p>
        </div>
        <Badge tone={p.status === "active" ? "accent" : p.status === "completed" ? "ok" : "warn"}>{roleLabel(p.status)}</Badge>
      </div>

      <StageRail stages={tracker.data.stages} />

      <Tabs tabs={tabs} value={tab} onChange={go} label="Project sections" />

      {tab === "overview" && (
        <GatePanel
          projectId={id}
          tracker={tracker.data}
          artifacts={artifacts.data ?? []}
          reload={() => {
            tracker.reload();
            artifacts.reload();
          }}
        />
      )}
      {tab === "audit" && <AuditSection projectId={id} stage={cur?.stage ?? ""} onEstimate={openEstimate} />}
      {tab === "brief" && <IntakeTab projectId={id} onEstimate={openEstimate} />}
      {tab === "infra" && <InfraTab projectId={id} />}
      {tab === "gaps" && <GapsTab projectId={id} />}
      {tab === "boq" && <BoqTab projectId={id} stage={cur?.stage ?? ""} autoEstimate={autoEstimate} />}
      {tab === "plan" && <PlanTab projectId={id} />}
      {tab === "field" && <FieldTab projectId={id} stage={cur?.stage ?? ""} />}
      {tab === "completion" && <CompletionTab projectId={id} stage={cur?.stage ?? ""} />}
      {tab === "overview" && <Members projectId={id} />}
      {tab === "overview" && tracker.data.stages.some((s) => s.decision) && (
        <div className="section">
          <h2>Approvals so far</h2>
          <table className="table">
            <tbody>
              {tracker.data.stages
                .filter((s) => s.decision)
                .map((s) => (
                  <tr key={s.stage}>
                    <td data-label="Stage">{stageName(s.stage)}</td>
                    <td data-label="Decision">
                      {s.decision?.decision} by {s.decision?.decided_by_name}
                    </td>
                    <td className="right" data-label="When">
                      {dateTime(s.decision?.decided_at)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
