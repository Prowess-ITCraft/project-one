"use client";
import { Back } from "@/components/kit";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { dateTime, get, post, type S } from "@/lib/api";
import { useData, useMe, useToast } from "@/lib/hooks";
import { discard, pending, queueAction, queueEvidence, subscribe, type FlushResult, type Pending } from "@/lib/offline";
import { Badge, Field, Notice, Skeleton, roleLabel, useAction } from "@/components/ui";
import { STATE_SHORT, TaskTimeline, shortTitle, stateTone } from "@/components/field";

type Detail = S["RunDetailOut"];

const todayKey = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
/** Time only for today's events; earlier ones keep their date so a two-day task reads right. */
function whenShort(iso: string): string {
  const full = dateTime(iso);
  const sameDay = new Date(iso).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }) === todayKey();
  return sameDay ? (full.split(", ").pop() ?? full) : full.replace(/ \d{4},/, ",");
}
type Run = S["RunOut"];
type Req = { type: string; label: string; required?: boolean; stage?: string };
type BaseField = { key: string; label: string; expected: string; severity?: string; how?: string };

const EVIDENCE_WINDOW: Record<string, string[]> = {
  check_in: ["accepted"],
  prechecks: ["checked_in"],
  work: ["prechecks_done", "configured"],
};
const BLOCKABLE = ["accepted", "checked_in", "prechecks_done", "configured", "engine_check"];

/** Where the phone is, if the engineer allows it. Never blocks the action. */
function locate(): Promise<{ lat?: number; lng?: number; accuracy_m?: number }> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) return resolve({});
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy) }),
      () => resolve({}),
      { timeout: 6000, maximumAge: 60_000 },
    );
  });
}

function EvidenceThumb({ fileId, label }: { fileId: string; label: string }) {
  const { data } = useData<S["DownloadOut"]>(`/files/${fileId}/download`);
  if (!data) return <span className="skel" style={{ width: 96, height: 72, display: "inline-block" }} />;
  return (
    <a href={data.url} target="_blank" rel="noreferrer">
      <img src={data.url} alt={label} />
    </a>
  );
}

/** One evidence requirement: what is needed, what was sent, and the control to add it. */
function EvidenceItem({
  run,
  index,
  req,
  have,
  queued,
  canAdd,
  onSent,
}: {
  run: Run;
  index: number;
  req: Req;
  have: S["EvidenceOut"][];
  queued: Pending[];
  canAdd: boolean;
  onSent: (r: FlushResult) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // Sent, but the task has not reloaded yet: keep the form away so it does not flash back and
  // invite a second upload. Back after ten seconds if the item never shows as added.
  const [sent, setSent] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const isFile = ["photo", "screenshot", "config_export"].includes(req.type);
  const done = have.length > 0;
  useEffect(() => {
    if (!sent) return;
    const t = setTimeout(() => setSent(false), 10_000);
    return () => clearTimeout(t);
  }, [sent]);

  async function send(file?: File | null) {
    setBusy(true);
    const r = await queueEvidence(run.id, index, req.label, {
      file,
      text: req.type === "serial" ? text.trim() : undefined,
      note: req.type === "note" ? text.trim() : undefined,
    });
    setBusy(false);
    setText("");
    setSent(!r.failed.length && !r.waiting);
    onSent(r);
  }

  return (
    <li>
      <div className="head">
        <span className="label">{req.label}</span>
        {done ? (
          <Badge tone="ok">Added</Badge>
        ) : queued.length ? (
          <Badge tone="warn">Saved on phone</Badge>
        ) : req.required === false ? (
          <Badge>Optional</Badge>
        ) : (
          <Badge>Needed</Badge>
        )}
      </div>
      {have.some((e) => e.file_id) && (
        <div className="thumbs">
          {have.filter((e) => e.file_id && e.type !== "config_export").map((e) => (
            <EvidenceThumb key={e.id} fileId={e.file_id as string} label={req.label} />
          ))}
          {have.filter((e) => e.type === "config_export").map((e) => (
            <span key={e.id} className="muted small">Configuration file added {dateTime(e.captured_at)}</span>
          ))}
        </div>
      )}
      {have.filter((e) => e.text_value || e.note).map((e) => (
        <p key={e.id} className="small">
          {e.text_value ?? e.note}
        </p>
      ))}
      {canAdd && !done && !queued.length && !sent && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          {isFile ? (
            <>
              <input
                ref={fileInput}
                type="file"
                hidden
                accept={req.type === "config_export" ? ".txt,.conf,.cfg,.json,.zip,.xml,.exp" : "image/*"}
                capture={req.type === "config_export" ? undefined : "environment"}
                aria-label={req.label}
                onChange={(e) => e.target.files?.[0] && void send(e.target.files[0])}
              />
              <button type="button" className="btn primary big" disabled={busy} onClick={() => fileInput.current?.click()}>
                {req.type === "photo" ? "Take photo" : req.type === "screenshot" ? "Add screenshot" : "Attach the file"}
              </button>
            </>
          ) : (
            <>
              <Field id={`ev-${index}`} label={req.type === "serial" ? "Serial number" : "What did you check?"}>
                {req.type === "serial" ? (
                  <input id={`ev-${index}`} value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />
                ) : (
                  <textarea id={`ev-${index}`} value={text} onChange={(e) => setText(e.target.value)} rows={2} />
                )}
              </Field>
              <button className="btn primary big" disabled={busy || text.trim().length < 2}>
                Save
              </button>
            </>
          )}
        </form>
      )}
    </li>
  );
}

/** Ask the customer for a code, then type it in. Used at check-in and at hand over. While
 * customer codes are switched off (ADR 0025) it is a single button. */
function CodeStep({
  run,
  purpose,
  action,
  label,
  onDone,
  waitFor,
  codes,
}: {
  run: Run;
  purpose: "check_in" | "handover";
  action: string;
  codes: boolean;
  label: string;
  onDone: (r: FlushResult) => void;
  /** Why the code cannot be asked for yet; the button stays off and says so. */
  waitFor?: string;
}) {
  const toast = useToast();
  const { busy, run: act } = useAction();
  const [sent, setSent] = useState<S["CodeSentOut"] | null>(null);
  const [code, setCode] = useState("");
  if (!codes) {
    return (
      <div className="stack">
        {waitFor && <p className="small muted">{waitFor}</p>}
        <button
          className="btn primary big"
          disabled={!!waitFor}
          onClick={async () => onDone(await queueAction(run.id, `/field/runs/${run.id}/${action}`, label, await locate()))}
        >
          {label}
        </button>
      </div>
    );
  }
  return (
    <div className="stack">
      {waitFor && !sent && <p className="small muted">{waitFor}</p>}
      <button
        className={`btn ${sent ? "" : "primary "}big`}
        disabled={busy || (!!waitFor && !sent)}
        onClick={async () => {
          const r = await act(() => post<S["CodeSentOut"]>(`/field/runs/${run.id}/codes/${purpose}`));
          if (r) {
            setSent(r);
            toast(`Code sent to ${r.sent_to}`);
          }
        }}
      >
        {sent ? "Send a new code" : "Send code to the customer"}
      </button>
      {sent && (
        <p className="small muted">
          Sent to {sent.sent_to}. Ask the customer to read it out. It works for {sent.valid_minutes} minutes.
        </p>
      )}
      <form
        className="otp"
        onSubmit={async (e) => {
          e.preventDefault();
          const where = await locate();
          onDone(await queueAction(run.id, `/field/runs/${run.id}/${action}`, label, { code, ...where }));
          setCode("");
        }}
      >
        <label className="small" htmlFor={`otp-${purpose}`} style={{ flexBasis: "100%" }}>
          Code from the customer
        </label>
        <input
          id={`otp-${purpose}`}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
        />
        <button className="btn primary" disabled={code.length !== 6}>
          {label}
        </button>
      </form>
    </div>
  );
}

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const { me, can } = useMe();
  const toast = useToast();
  const d = useData<Detail>(`/field/runs/${id}`);
  const { busy, run: act } = useAction();
  const [queued, setQueued] = useState<Pending[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [blockOpen, setBlockOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [verdict, setVerdict] = useState<"approve" | "reject" | null>(null);
  const [team, setTeam] = useState<S["MemberOut"][]>([]);
  const [reassignTo, setReassignTo] = useState("");

  useEffect(() => {
    const read = () => void pending(id).then(setQueued);
    read();
    return subscribe(read);
  }, [id]);

  const run = d.data?.run;
  useEffect(() => {
    if (!run) return;
    setValues(Object.fromEntries(Object.entries(run.actuals).map(([k, v]) => [k, String((v as { value?: string }).value ?? "")])));
  }, [run]);
  useEffect(() => {
    if (run && can("field:manage")) void get<S["MemberOut"][]>(`/projects/${run.project_id}/members`).then(setTeam).catch(() => setTeam([]));
  }, [run, can]);

  function after(r: FlushResult) {
    if (r.failed.length) toast(r.failed[r.failed.length - 1], true);
    else if (r.waiting) toast("No signal. Saved on this phone; it will be sent when you are back online.");
    d.reload();
  }
  async function doAction(path: string, label: string, body: Record<string, unknown> = {}) {
    after(await queueAction(id, `/field/runs/${id}/${path}`, label, body));
  }

  if (d.error) return <Notice tone="bad">{d.error}</Notice>;
  if (!d.data || !run) return <Skeleton lines={10} />;
  const detail = d.data;
  const mine = run.assignee_id === me.id && can("field:work");
  const reqs = run.evidence_reqs as Req[];
  const baseline = run.baseline as BaseField[];
  const evidenceFor = (i: number) => detail.evidence.filter((e) => e.requirement_index === i);
  const queuedFor = (i: number) => queued.filter((q) => q.fields?.requirement_index === String(i));
  const stageItems = (stage: string) =>
    reqs.map((r, i) => ({ r, i })).filter(({ r }) => (r.stage ?? "work") === stage);
  const lastCheck = detail.checks[detail.checks.length - 1];
  const nextStep = run.steps.findIndex((s) => !s.done);
  const failedQueue = queued.filter((q) => q.error);

  const evidenceBlock = (stage: string) => (
    <ul className="evidence-list">
      {stageItems(stage).map(({ r, i }) => (
        <EvidenceItem
          key={i}
          run={run}
          index={i}
          req={r}
          have={evidenceFor(i)}
          queued={queuedFor(i)}
          canAdd={mine && EVIDENCE_WINDOW[stage].includes(run.state)}
          onSent={after}
        />
      ))}
    </ul>
  );

  return (
    <div className="field-page">
      <div className="page-head">
        <div>
          {can("field:work") ? (
            <Back href="/field" label="My tasks" />
          ) : (
            <Back href={`/projects/${run.project_id}#field`} label="the project's field work" />
          )}
          <h1 className="task-title">
            <span className="mono muted">{run.task_ref}</span> {shortTitle(run.title, run.asset)}
          </h1>
          {detail.project && (
            <p className="task-where">
              {detail.project.customer ? `${detail.project.customer}, ` : ""}
              {detail.project.name} <span className="mono muted">{detail.project.code}</span>
            </p>
          )}
          <p>
            {run.asset ? <span className="mono">{run.asset}</span> : "No device"}
            {run.requires_downtime ? ", needs downtime" : ""}. Planned {dateTime(run.planned_start)}.
          </p>
          {d.stale && <Notice tone="warn">No signal. This is what was loaded earlier; anything you do is saved on this phone and sent when signal returns.</Notice>}
        </div>
        <Badge tone={stateTone(run.state)}>{STATE_SHORT[run.state]}</Badge>
      </div>

      <TaskTimeline run={run} />
      <p className="next-action" aria-live="polite">
        {detail.next_action}
      </p>

      {queued.length > 0 && (
        <div className="outbox-note stack">
          <span>
            {queued.length - failedQueue.length > 0 &&
              `${queued.length - failedQueue.length} action(s) saved on this phone, waiting for signal. `}
            {failedQueue.length > 0 && "These were refused by the server:"}
          </span>
          {failedQueue.map((q) => (
            <div key={q.id} className="row between small">
              <span>
                {q.label}: {q.error}
              </span>
              <button className="btn quiet small" onClick={() => void discard(q.id)}>
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      {/* ------------------------------------------------ the engineer's next action */}
      {mine && (
        <div className="section stack">
          {run.state === "assigned" && (
            <button className="btn primary big" onClick={() => void doAction("accept", "Accept task")}>
              Accept task
            </button>
          )}

          {run.state === "accepted" && (
            <>
              {detail.waiting_on.length > 0 ? (
                <Notice tone="warn">
                  Check-in opens when {detail.waiting_on.join(", ")} is handed over. Nothing to do until then.
                </Notice>
              ) : (
                <>
                  <h2>Arrive on site</h2>
                  {evidenceBlock("check_in")}
                  <CodeStep
                    run={run}
                    purpose="check_in"
                    action="check-in"
                    label="Check in"
                    onDone={after}
                    codes={detail.customer_codes}
                    waitFor={
                      stageItems("check_in").some(({ i }) => !evidenceFor(i).length && !queuedFor(i).length)
                        ? detail.customer_codes
                          ? "Add the arrival evidence above first, then ask the customer for the code."
                          : "Add the arrival evidence above first."
                        : undefined
                    }
                  />
                </>
              )}
              <button
                className="btn quiet"
                onClick={async () => void doAction("depart", "On my way", await locate())}
              >
                I am on my way
              </button>
            </>
          )}

          {run.state === "checked_in" && (
            <>
              <h2>Before you change anything</h2>
              <p className="muted">Confirm a backup exists and that you have admin access with the customer present.</p>
              {evidenceBlock("prechecks")}
              <button
                className="btn primary big"
                disabled={stageItems("prechecks").some(({ i }) => !evidenceFor(i).length && !queuedFor(i).length)}
                onClick={() => void doAction("prechecks-done", "Prechecks done")}
              >
                Mark prechecks done
              </button>
            </>
          )}

          {(run.state === "prechecks_done" || run.state === "configured") && (
            <>
              {run.state === "prechecks_done" && (
                <>
                  <h2>Steps</h2>
                  <ol className="steps">
                    {run.steps.map((s, i) => (
                      <li key={i} data-done={s.done} data-next={i === nextStep}>
                        <span className="text">{String(s.text)}</span>
                        {i === nextStep ? (
                          <button className="btn primary small" onClick={() => void doAction(`steps/${i}`, `Step ${i + 1} done`)}>
                            Done
                          </button>
                        ) : (
                          <span />
                        )}
                      </li>
                    ))}
                  </ol>
                </>
              )}
              {baseline.length > 0 && (
                <form
                  className="values"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const changed = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()));
                    void doAction("values", "Values recorded", { values: changed });
                  }}
                >
                  <h2>What the device shows</h2>
                  <p className="muted small">Type what you see on the device for each setting, not what it should be.</p>
                  {baseline.map((f) => (
                    <Field key={f.key} id={`v-${f.key}`} label={f.label} hint={`Target: ${f.expected}${f.severity ? `. ${roleLabel(f.severity)}` : ""}`}>
                      <input
                        id={`v-${f.key}`}
                        value={values[f.key] ?? ""}
                        onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                        autoComplete="off"
                      />
                    </Field>
                  ))}
                  <div>
                    <button className="btn">Save values</button>
                  </div>
                </form>
              )}
              {run.state === "prechecks_done" && (
                <button
                  className="btn primary big"
                  disabled={nextStep !== -1 || baseline.some((f) => !(f.key in run.actuals))}
                  onClick={() => void doAction("configured", "Configured")}
                >
                  Mark configured
                </button>
              )}
              {run.state === "configured" && (
                <>
                  {lastCheck && !lastCheck.passed && (
                    <Notice tone="bad">
                      The last check failed:{" "}
                      {(lastCheck.result.fields as { label: string; outcome: string; reason: string }[])
                        .filter((f) => f.outcome === "fail")
                        .map((f) => `${f.label} (${f.reason})`)
                        .join("; ")}
                    </Notice>
                  )}
                  <h2>Evidence</h2>
                  {evidenceBlock("work")}
                  <button
                    className="btn primary big"
                    disabled={stageItems("work").some(({ r, i }) => r.required !== false && !evidenceFor(i).length)}
                    onClick={() => void doAction("submit-evidence", "Send for the check")}
                  >
                    Send for the check
                  </button>
                </>
              )}
            </>
          )}

          {run.state === "engine_check" && (
            <>
              <h2>Hand over to the customer</h2>
              <p className="muted">
                Show the customer the finished work{detail.customer_codes ? ", then ask for the hand over code" : ", then confirm the hand over"}.
              </p>
              <CodeStep run={run} purpose="handover" action="hand-over" label="Confirm hand over" onDone={after} codes={detail.customer_codes} />
            </>
          )}

          {BLOCKABLE.includes(run.state) &&
            (blockOpen ? (
              <div className="stack">
                <Field id="block" label="What stops you?" hint="The project manager and the Director are told at once.">
                  <textarea id="block" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
                <div className="row">
                  <button
                    className="btn danger"
                    disabled={reason.trim().length < 3}
                    onClick={async () => {
                      await doAction("block", "Blocked", { reason: reason.trim() });
                      setBlockOpen(false);
                      setReason("");
                    }}
                  >
                    Report block
                  </button>
                  <button className="btn quiet" onClick={() => setBlockOpen(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button className="btn quiet" onClick={() => setBlockOpen(true)}>
                I cannot continue
              </button>
            ))}
        </div>
      )}

      {/* ------------------------------------------------ manager */}
      {can("field:manage") && (run.state === "blocked" || ["assigned", "accepted"].includes(run.state)) && (
        <div className="section stack">
          <h2>Manage</h2>
          {run.state === "blocked" && (
            <>
              <Notice tone="bad">Blocked: {run.block_reason}</Notice>
              <Field id="unblock" label="What was decided?" hint="The engineer continues from where they stopped.">
                <textarea id="unblock" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
              <div>
                <button
                  className="btn primary"
                  disabled={busy || reason.trim().length < 3}
                  onClick={async () => {
                    await act(() => post(`/field/runs/${id}/unblock`, { note: reason.trim() }), "Unblocked");
                    setReason("");
                    d.reload();
                  }}
                >
                  Unblock
                </button>
              </div>
            </>
          )}
          {(["assigned", "accepted"].includes(run.state) || run.blocked_from === "accepted") && (
            <div className="row">
              <select aria-label="Engineer" value={reassignTo} onChange={(e) => setReassignTo(e.target.value)} style={{ maxWidth: 260 }}>
                <option value="">Hand to another engineer</option>
                {team
                  .filter((m) => m.project_role === "field_engineer" && m.user_id !== run.assignee_id)
                  .map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name}
                    </option>
                  ))}
              </select>
              <button
                className="btn"
                disabled={!reassignTo || busy}
                onClick={async () => {
                  await act(
                    () => post(`/field/runs/${id}/reassign`, { assignee_id: reassignTo, reason: "Reassigned by the project manager" }),
                    "Reassigned",
                  );
                  setReassignTo("");
                  d.reload();
                }}
              >
                Reassign
              </button>
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------ verifier */}
      {can("field:verify") && run.state === "verifier_review" && (
        <div className="section stack">
          <h2>Verify</h2>
          {run.assignee_id === me.id ? (
            <Notice>You did this work, so another verifier has to check it.</Notice>
          ) : verdict === "reject" ? (
            <>
              <Field id="why" label="What must be fixed?" hint="The engineer sees this and the task goes back to configured.">
                <textarea id="why" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
              <div className="row">
                <button
                  className="btn danger"
                  disabled={busy || reason.trim().length < 5}
                  onClick={async () => {
                    await act(() => post(`/field/runs/${id}/decision`, { decision: "reject", reason: reason.trim() }), "Sent back");
                    setVerdict(null);
                    setReason("");
                    d.reload();
                  }}
                >
                  Send back
                </button>
                <button className="btn quiet" onClick={() => setVerdict(null)}>
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <div className="row">
              <button
                className="btn primary"
                disabled={busy}
                onClick={async () => {
                  await act(() => post(`/field/runs/${id}/decision`, { decision: "approve" }), "Verified and closed");
                  d.reload();
                }}
              >
                Approve and close
              </button>
              <button className="btn" onClick={() => setVerdict("reject")}>
                Send back
              </button>
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------ the record */}
      {lastCheck && (
        <div className="section">
          <h2>
            Configuration check {lastCheck.attempt}: {lastCheck.passed ? "passed" : "failed"}
          </h2>
          <table className="table check-result">
            <thead>
              <tr>
                <th>Setting</th>
                <th>Target</th>
                <th>Found</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {(lastCheck.result.fields as { key: string; label: string; expected: string; actual: string | null; outcome: string; reason: string }[]).map((f) => (
                <tr key={f.key}>
                  <td data-label="Setting">{f.label}</td>
                  <td data-label="Target">{f.expected}</td>
                  <td data-label="Found">{f.actual ?? "Not recorded"}</td>
                  <td data-label="Result">
                    <span className={f.outcome}>{f.outcome === "not_checked" ? "Verifier decides" : f.outcome === "pass" ? "Pass" : "Fail"}</span>
                    <div className="muted small">{f.reason}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!mine && (
        <div className="section">
          <h2>Evidence</h2>
          {detail.evidence.length === 0 ? (
            <p className="muted">No evidence yet.</p>
          ) : (
            <ul className="evidence-list">
              {reqs.map((r, i) =>
                evidenceFor(i).length ? (
                  <EvidenceItem key={i} run={run} index={i} req={r} have={evidenceFor(i)} queued={[]} canAdd={false} onSent={after} />
                ) : null,
              )}
            </ul>
          )}
        </div>
      )}

      <div className="section">
        <div className="row between">
          <h2>History</h2>
          <a className="btn quiet small" href={`/api/v1/field/runs/${id}/render?fmt=pdf`}>
            Download the task record (PDF)
          </a>
        </div>
        <ul className="feed">
          {[...detail.events].reverse().map((e) => (
            <li key={e.seq}>
              <time dateTime={e.captured_at ?? e.at}>{whenShort(e.captured_at ?? e.at)}</time>
              <span>
                {e.action.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
                {e.to_state && e.to_state !== e.from_state ? `, now ${STATE_SHORT[e.to_state] ?? e.to_state}` : ""}
                {typeof e.detail.reason === "string" ? `: ${e.detail.reason}` : ""}
                {typeof e.detail.label === "string" ? `: ${e.detail.label}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
