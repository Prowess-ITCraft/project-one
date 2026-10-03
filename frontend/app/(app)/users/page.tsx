"use client";
import { useState } from "react";
import { dateTime, patch, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, roleLabel, useAction } from "@/components/ui";

type Page<T> = { items: T[]; total: number };
const ROLES = [
  "audit_engineer",
  "solution_architect",
  "technical_lead",
  "sales_manager",
  "sales_head",
  "project_manager",
  "field_engineer",
  "director",
  "admin",
];

function NewUser({ onDone }: { onDone: () => void }) {
  const { busy, run } = useAction();
  const [f, setF] = useState({ full_name: "", email: "", initials: "", password: "", role: "audit_engineer" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    const r = await run(
      () => post("/users", { full_name: f.full_name, email: f.email, initials: f.initials, password: f.password, roles: [f.role] }),
      "User created",
    );
    if (r !== undefined) onDone();
  }
  return (
    <form className="section" onSubmit={submit}>
      <h2>New user</h2>
      <p className="lede">Share the temporary password in person. Directors and admins set up an authenticator at first sign-in.</p>
      <div className="grid2">
        <Field id="n" label="Full name">
          <input id="n" type="text" required value={f.full_name} onChange={set("full_name")} />
        </Field>
        <Field id="e" label="Work email">
          <input id="e" type="email" required value={f.email} onChange={set("email")} />
        </Field>
        <Field id="i" label="Initials" hint="Used in quote numbers, for example NN">
          <input id="i" type="text" required pattern="[A-Za-z]{1,6}" value={f.initials} onChange={set("initials")} />
        </Field>
        <Field id="r" label="Role">
          <select id="r" value={f.role} onChange={set("role")}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
        </Field>
        <Field id="p" label="Temporary password" hint="At least 12 characters. Not the name or email.">
          <input id="p" type="password" required minLength={12} autoComplete="new-password" value={f.password} onChange={set("password")} />
        </Field>
      </div>
      <div className="row">
        <button className="btn primary" disabled={busy}>
          {busy ? "Creating" : "Create user"}
        </button>
        <button type="button" className="btn quiet" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function Users() {
  const { can, me } = useMe();
  const users = useData<Page<S["UserOut"]>>(can("user:read") ? "/users?size=200" : null);
  const [creating, setCreating] = useState(false);
  const { busy, run } = useAction();

  if (!can("user:manage")) return <Notice tone="warn">Only admins manage users.</Notice>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Users</h1>
          <p>Who can sign in, and what they can do.</p>
        </div>
        {!creating && (
          <button className="btn primary" onClick={() => setCreating(true)}>
            New user
          </button>
        )}
      </div>
      {creating && (
        <NewUser
          onDone={() => {
            setCreating(false);
            users.reload();
          }}
        />
      )}
      {users.loading && !users.data && <Skeleton lines={6} />}
      {users.error && <Notice tone="bad">{users.error}</Notice>}
      {users.data && users.data.items.length === 0 && <Empty title="No users">Create the first user.</Empty>}
      {users.data && users.data.items.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Person</th>
              <th>Roles</th>
              <th>Status</th>
              <th className="right">Last sign-in</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.data.items.map((u) => (
              <tr key={u.id}>
                <td data-label="Person">
                  {u.full_name}
                  <div className="muted small">{u.email}</div>
                </td>
                <td data-label="Roles">{u.roles.map(roleLabel).join(", ")}</td>
                <td data-label="Status">
                  {!u.is_active ? <Badge tone="bad">Deactivated</Badge> : u.locked_until ? <Badge tone="warn">Locked</Badge> : <Badge tone="ok">Active</Badge>}
                </td>
                <td data-label="Last sign-in" className="right">
                  {u.last_login_at ? dateTime(u.last_login_at) : "Never"}
                </td>
                <td className="right">
                  {u.locked_until && (
                    <button
                      className="btn small"
                      disabled={busy}
                      onClick={async () => {
                        await run(() => post(`/users/${u.id}/unlock`), "Account unlocked");
                        users.reload();
                      }}
                    >
                      Unlock
                    </button>
                  )}
                  {u.id !== me.id && (
                    <button
                      className="btn quiet small"
                      disabled={busy}
                      onClick={async () => {
                        await run(() => patch(`/users/${u.id}`, { is_active: !u.is_active, version: u.version }), u.is_active ? "User deactivated" : "User reactivated");
                        users.reload();
                      }}
                    >
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
