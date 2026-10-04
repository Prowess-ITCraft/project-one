"use client";
import { useMemo, useState } from "react";
import { dateTime, patch, post, put, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, useAction } from "@/components/ui";
import { Check, Drawer, Tabs } from "@/components/kit";

type Page<T> = { items: T[]; total: number };
type User = S["UserOut"];

/** Staff roles in the order work flows through a project. Customer contacts are added from the
 * customer's page, not here. */
const ROLES: { id: string; label: string; does: string }[] = [
  { id: "sales_manager", label: "Sales manager", does: "Customers, projects, BOQs and quotations" },
  { id: "sales_head", label: "Sales head", does: "Approves BOQs and quotations, assigns the team" },
  { id: "audit_engineer", label: "Audit engineer", does: "Imports PrismSuite reports, fills the questionnaire" },
  { id: "solution_architect", label: "Solution architect", does: "Current and ideal IT, gap analysis" },
  { id: "project_manager", label: "Project manager", does: "Plans the work, assigns field tasks, asks for waivers" },
  { id: "field_engineer", label: "Field engineer", does: "Does the tasks on site from a phone. Sees no prices" },
  { id: "technical_lead", label: "Technical lead / verifier", does: "Reviews and verifies field work" },
  { id: "director", label: "Director", does: "Approves waivers, signs certificates. Needs an authenticator" },
  { id: "admin", label: "Admin", does: "Manages accounts and settings. Needs an authenticator" },
];
const LABEL = Object.fromEntries(ROLES.map((r) => [r.id, r.label]));
const MFA_ROLES = new Set(["director", "admin"]);
const hasRole = (u: User, r: string) => (u.roles as string[]).includes(r);
const roleName = (r: string) => LABEL[r] ?? r.replace(/_/g, " ");
const ORDER = ROLES.map((r) => r.id);
/** A person's roles in the order work flows, the same order as the role list. */
const rolesText = (u: User) =>
  [...u.roles].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)).map(roleName).join(", ");

/** 16 characters from an alphabet without look-alikes (no 0/O, 1/l/I), always mixed. */
function newPassword(): string {
  const sets = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789", "#%+=?@"];
  const all = sets.join("");
  const rnd = (n: number) => crypto.getRandomValues(new Uint32Array(1))[0] % n;
  const chars = sets.map((s) => s[rnd(s.length)]);
  while (chars.length < 16) chars.push(all[rnd(all.length)]);
  for (let i = chars.length - 1; i > 0; i--) {
    const j = rnd(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .replace(/[^A-Za-z]/g, "")
    .slice(0, 3)
    .toUpperCase();
}

function status(u: User) {
  if (!u.is_active) return <Badge tone="bad">Deactivated</Badge>;
  if (u.locked_until && new Date(u.locked_until) > new Date()) return <Badge tone="warn">Locked</Badge>;
  return <Badge tone="ok">Active</Badge>;
}

function RolePicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset className="role-pick">
      <legend>Roles</legend>
      {ROLES.map((r) => (
        <Check
          key={r.id}
          checked={value.includes(r.id)}
          onChange={(on) => onChange(on ? [...value, r.id] : value.filter((x) => x !== r.id))}
        >
          <span>
            {r.label}
            <span className="muted small"> {r.does}</span>
          </span>
        </Check>
      ))}
    </fieldset>
  );
}

/** A password shown once, to be handed over in person. */
function Secret({ email, password }: { email: string; password: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="handover">
      <p>
        Give these to the person in person. The password is not shown again; they can change it after
        signing in.
      </p>
      <dl className="kv">
        <dt>Email</dt>
        <dd>{email}</dd>
        <dt>Temporary password</dt>
        <dd>
          <code className="secret">{password}</code>{" "}
          <button
            type="button"
            className="btn quiet small"
            onClick={async () => {
              await navigator.clipboard?.writeText(password);
              setCopied(true);
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </dd>
      </dl>
    </div>
  );
}

function NewAccount({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { busy, run } = useAction();
  const [f, setF] = useState({ full_name: "", email: "", initials: "", designation: "", phone: "" });
  const [roles, setRoles] = useState<string[]>([]);
  const [password, setPassword] = useState(newPassword);
  const [done, setDone] = useState<{ email: string; password: string } | null>(null);
  const [initialsTouched, setInitialsTouched] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setF((old) => ({
      ...old,
      [k]: v,
      ...(k === "full_name" && !initialsTouched ? { initials: initialsOf(v) } : {}),
    }));
  };

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    const r = await run(
      () =>
        post("/users", {
          full_name: f.full_name.trim(),
          email: f.email.trim(),
          initials: f.initials,
          designation: f.designation.trim() || null,
          phone: f.phone.trim() || null,
          password,
          roles,
        }),
      "Account created",
    );
    if (r !== undefined) {
      setDone({ email: f.email.trim(), password });
      onCreated();
    }
  }

  return (
    <Drawer title={done ? "Account created" : "New account"} onClose={onClose}>
      {done ? (
        <>
          <Secret {...done} />
          {roles.some((r) => MFA_ROLES.has(r)) && (
            <Notice tone="warn">At first sign-in they will be asked to set up an authenticator app.</Notice>
          )}
          <div className="row">
            <button className="btn primary" onClick={onClose}>
              Done
            </button>
          </div>
        </>
      ) : (
        <form className="stack" onSubmit={submit}>
          <div className="grid2">
            <Field id="n" label="Full name">
              <input id="n" type="text" required minLength={2} value={f.full_name} onChange={set("full_name")} />
            </Field>
            <Field id="e" label="Work email">
              <input id="e" type="email" required value={f.email} onChange={set("email")} />
            </Field>
            <Field id="i" label="Initials" hint="Used in quote numbers, for example CS">
              <input
                id="i"
                type="text"
                required
                pattern="[A-Za-z]{1,6}"
                value={f.initials}
                onChange={(e) => {
                  setInitialsTouched(true);
                  set("initials")(e);
                }}
              />
            </Field>
            <Field id="d" label="Designation" hint="Optional, for example Sales manager">
              <input id="d" type="text" value={f.designation} onChange={set("designation")} />
            </Field>
            <Field id="ph" label="Phone" hint="Optional">
              <input id="ph" type="tel" value={f.phone} onChange={set("phone")} />
            </Field>
          </div>
          <RolePicker value={roles} onChange={setRoles} />
          <Field id="p" label="Temporary password" hint="At least 12 characters. A strong one is filled in for you.">
            <div className="row">
              <input
                id="p"
                type="text"
                className="mono"
                required
                minLength={12}
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button type="button" className="btn quiet small" onClick={() => setPassword(newPassword())}>
                New password
              </button>
            </div>
          </Field>
          <div className="row">
            <button className="btn primary" disabled={busy || roles.length === 0}>
              {busy ? "Creating" : "Create account"}
            </button>
            <button type="button" className="btn quiet" onClick={onClose}>
              Cancel
            </button>
            {roles.length === 0 && <span className="muted small">Pick at least one role.</span>}
          </div>
        </form>
      )}
    </Drawer>
  );
}

function Account({ user, isMe, onClose, onChanged }: { user: User; isMe: boolean; onClose: () => void; onChanged: () => void }) {
  const { busy, run } = useAction();
  const [u, setU] = useState(user);
  const [f, setF] = useState({ full_name: u.full_name, initials: u.initials, designation: u.designation ?? "", phone: u.phone ?? "" });
  const [roles, setRoles] = useState<string[]>(u.roles);
  const [secret, setSecret] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const detailsChanged =
    f.full_name !== u.full_name || f.initials !== u.initials || f.designation !== (u.designation ?? "") || f.phone !== (u.phone ?? "");
  const rolesChanged = [...roles].sort().join() !== [...u.roles].sort().join();

  async function apply(fn: () => Promise<User>, msg: string) {
    const r = await run(fn, msg);
    if (r) {
      setU(r);
      onChanged();
    }
    return r;
  }

  return (
    <Drawer title={u.full_name} onClose={onClose}>
      <div className="row">
        {status(u)}
        {u.mfa_enabled ? <Badge tone="ok">Authenticator set up</Badge> : <Badge>No authenticator</Badge>}
        <span className="muted small">Last sign-in {u.last_login_at ? dateTime(u.last_login_at) : "never"}</span>
      </div>
      <p className="muted small">{u.email}</p>

      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          await apply(
            () =>
              patch<User>(`/users/${u.id}`, {
                version: u.version,
                full_name: f.full_name.trim(),
                initials: f.initials,
                designation: f.designation.trim() || null,
                phone: f.phone.trim() || null,
              }),
            "Details saved",
          );
        }}
      >
        <h3>Details</h3>
        <div className="grid2">
          <Field id="an" label="Full name">
            <input id="an" type="text" required minLength={2} value={f.full_name} onChange={set("full_name")} />
          </Field>
          <Field id="ai" label="Initials">
            <input id="ai" type="text" required pattern="[A-Za-z]{1,6}" value={f.initials} onChange={set("initials")} />
          </Field>
          <Field id="ad" label="Designation">
            <input id="ad" type="text" value={f.designation} onChange={set("designation")} />
          </Field>
          <Field id="ap" label="Phone">
            <input id="ap" type="tel" value={f.phone} onChange={set("phone")} />
          </Field>
        </div>
        <div className="row">
          <button className="btn" disabled={busy || !detailsChanged}>
            Save details
          </button>
        </div>
      </form>

      <div className="stack">
        <h3>Roles</h3>
        <RolePicker value={roles} onChange={setRoles} />
        {isMe && hasRole(u, "admin") && !roles.includes("admin") && (
          <Notice tone="warn">You cannot remove your own admin role. Ask another admin.</Notice>
        )}
        <div className="row">
          <button
            className="btn"
            disabled={busy || !rolesChanged || roles.length === 0}
            onClick={() => apply(() => put<User>(`/users/${u.id}/roles`, { version: u.version, roles }), "Roles saved")}
          >
            Save roles
          </button>
          {roles.length === 0 && <span className="muted small">Keep at least one role.</span>}
        </div>
      </div>

      <div className="stack">
        <h3>Access</h3>
        {secret && <Secret email={u.email} password={secret} />}
        <div className="row">
          <button
            className="btn"
            disabled={busy}
            onClick={async () => {
              const pw = newPassword();
              const r = await run(async () => {
                await post(`/users/${u.id}/reset-password`, { new_password: pw });
                return true;
              }, "Password reset");
              if (r) setSecret(pw);
            }}
          >
            Reset password
          </button>
          {u.mfa_enabled && (
            <button className="btn" disabled={busy} onClick={() => apply(() => post<User>(`/users/${u.id}/reset-mfa`), "Authenticator reset")}>
              Reset authenticator
            </button>
          )}
          {u.locked_until && (
            <button className="btn" disabled={busy} onClick={() => apply(() => post<User>(`/users/${u.id}/unlock`), "Account unlocked")}>
              Unlock
            </button>
          )}
          {!isMe && (
            <button
              className="btn quiet"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await post(`/users/${u.id}/sessions/revoke-all`);
                  return true;
                }, "Signed out everywhere")
              }
            >
              Sign out everywhere
            </button>
          )}
        </div>
        {!isMe && (
          <div className="row">
            <button
              className={`btn ${u.is_active ? "danger" : ""}`}
              disabled={busy}
              onClick={() =>
                apply(
                  () => patch<User>(`/users/${u.id}`, { version: u.version, is_active: !u.is_active }),
                  u.is_active ? "Account deactivated" : "Account reactivated",
                )
              }
            >
              {u.is_active ? "Deactivate account" : "Reactivate account"}
            </button>
            <span className="muted small">
              {u.is_active ? "They can no longer sign in. Their history stays." : "They can sign in again."}
            </span>
          </div>
        )}
      </div>
    </Drawer>
  );
}

export default function Users() {
  const { can, me } = useMe();
  const users = useData<Page<User>>(can("user:read") ? "/users?size=200" : null);
  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const staff = useMemo(() => (users.data?.items ?? []).filter((u) => !hasRole(u, "customer_rep")), [users.data]);
  const count = (r: string) => staff.filter((u) => hasRole(u, r)).length;
  const shown = staff
    .filter((u) => tab === "all" || (tab === "inactive" ? !u.is_active : u.is_active && hasRole(u, tab)))
    .filter((u) => !q || `${u.full_name} ${u.email} ${u.designation ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => a.full_name.localeCompare(b.full_name));
  const open = staff.find((u) => u.id === openId);

  if (!can("user:manage")) return <Notice tone="warn">Only admins manage accounts.</Notice>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Accounts</h1>
          <p>Who can sign in, and what each person can do.</p>
        </div>
        <button className="btn primary" onClick={() => setCreating(true)}>
          New account
        </button>
      </div>
      {users.loading && !users.data && <Skeleton lines={6} />}
      {users.error && <Notice tone="bad">{users.error}</Notice>}
      {users.data && (
        <>
          <Tabs
            label="Accounts by role"
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "all", label: "Everyone", count: staff.length },
              ...ROLES.filter((r) => count(r.id) > 0).map((r) => ({ id: r.id, label: r.label, count: count(r.id) })),
              ...(staff.some((u) => !u.is_active) ? [{ id: "inactive", label: "Deactivated", count: staff.filter((u) => !u.is_active).length }] : []),
            ]}
          />
          <div className="filters">
            <input type="search" placeholder="Search name, email or designation" aria-label="Search accounts" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {shown.length === 0 ? (
            <Empty title={staff.length === 0 ? "No accounts yet" : "Nobody matches"}>
              {staff.length === 0 ? "Create the first account." : "Try another role or search."}
            </Empty>
          ) : (
            <table className="table accounts">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Roles</th>
                  <th>Status</th>
                  <th className="right">Last sign-in</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((u) => (
                  <tr key={u.id}>
                    <td data-label="Person">
                      <button className="linklike" onClick={() => setOpenId(u.id)}>
                        {u.full_name}
                      </button>
                      <div className="muted small">
                        {u.email}
                        {u.designation ? `, ${u.designation}` : ""}
                      </div>
                    </td>
                    <td data-label="Roles">{rolesText(u)}</td>
                    <td data-label="Status">{status(u)}</td>
                    <td data-label="Last sign-in" className="right">
                      {u.last_login_at ? dateTime(u.last_login_at) : "Never"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
      {creating && <NewAccount onClose={() => setCreating(false)} onCreated={users.reload} />}
      {open && (
        <Account
          key={open.id}
          user={open}
          isMe={open.id === me.id}
          onClose={() => setOpenId(null)}
          onChanged={users.reload}
        />
      )}
    </>
  );
}
