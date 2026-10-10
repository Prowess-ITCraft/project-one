"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { date, del, patch, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, stageName, useAction } from "@/components/ui";
import { Back, Check, ConfirmButton } from "@/components/kit";
import { CustomerForm } from "@/components/customers";

type Page<T> = { items: T[]; total: number };

function Contacts({ customerId, canWrite }: { customerId: string; canWrite: boolean }) {
  const list = useData<S["ContactOut"][]>(`/customers/${customerId}/contacts`);
  const { busy, run } = useAction();
  const blank = { full_name: "", designation: "", email: "", phone: "", is_primary: false, can_sign_off: false };
  const [f, setF] = useState(blank);
  const [adding, setAdding] = useState(false);
  return (
    <div className="section stack">
      <div className="row between">
        <h2>Contacts</h2>
        {canWrite && !adding && (
          <button className="btn" onClick={() => setAdding(true)}>
            Add contact
          </button>
        )}
      </div>
      <p className="muted small">
        A contact who can sign off receives the customer codes and acknowledgement links. Field engineers never see
        contact details.
      </p>
      {adding && (
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await run(
              () =>
                post(`/customers/${customerId}/contacts`, {
                  ...f,
                  designation: f.designation || null,
                  email: f.email || null,
                  phone: f.phone || null,
                }),
              "Contact added",
            );
            if (r !== undefined) {
              setF(blank);
              setAdding(false);
              void list.reload();
            }
          }}
        >
          <div className="form-grid">
            <Field id="ct-name" label="Name">
              <input id="ct-name" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
            </Field>
            <Field id="ct-des" label="Designation">
              <input id="ct-des" value={f.designation} onChange={(e) => setF({ ...f, designation: e.target.value })} />
            </Field>
            <Field id="ct-email" label="Email">
              <input id="ct-email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
            </Field>
            <Field id="ct-phone" label="Phone">
              <input id="ct-phone" type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
            </Field>
          </div>
          <div className="row">
            <Check checked={f.is_primary} onChange={(v) => setF({ ...f, is_primary: v })}>
              Main contact
            </Check>
            <Check checked={f.can_sign_off} onChange={(v) => setF({ ...f, can_sign_off: v })}>
              Can sign off work
            </Check>
          </div>
          <div className="row">
            <button className="btn primary" disabled={busy || f.full_name.trim().length < 2 || (f.can_sign_off && !f.email)}>
              Save contact
            </button>
            <button type="button" className="btn quiet" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
          {f.can_sign_off && !f.email && <p className="small muted">A contact who signs off needs an email address.</p>}
        </form>
      )}
      {!list.data ? (
        <Skeleton lines={3} />
      ) : list.data.length === 0 ? (
        <p className="muted">No contacts yet.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email and phone</th>
              <th>Role</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.data.map((c) => (
              <tr key={c.id}>
                <td data-label="Name">
                  {c.full_name}
                  <div className="muted small">{c.designation ?? ""}</div>
                </td>
                <td data-label="Email and phone">
                  {c.email ?? ""}
                  <div className="muted small">{c.phone ?? ""}</div>
                </td>
                <td data-label="Role">
                  {c.is_primary && <Badge>Main</Badge>} {c.can_sign_off && <Badge tone="accent">Signs off</Badge>}
                </td>
                <td>
                  {canWrite && (
                    <span className="row">
                      <button
                        className="btn quiet small"
                        disabled={busy}
                        onClick={async () => {
                          await run(
                            () => patch(`/customers/${customerId}/contacts/${c.id}`, { can_sign_off: !c.can_sign_off, version: c.version }),
                            c.can_sign_off ? "No longer signs off" : "Can sign off now",
                          );
                          void list.reload();
                        }}
                      >
                        {c.can_sign_off ? "Stop sign-off" : "Allow sign-off"}
                      </button>
                      <ConfirmButton
                        className="btn quiet small"
                        question={`Remove ${c.full_name}?`}
                        confirmLabel="Remove"
                        onConfirm={async () => {
                          await run(() => del(`/customers/${customerId}/contacts/${c.id}`), "Contact removed");
                          void list.reload();
                        }}
                      >
                        Remove
                      </ConfirmButton>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Sites({ customerId, canWrite }: { customerId: string; canWrite: boolean }) {
  const list = useData<S["SiteOut"][]>(`/customers/${customerId}/sites`);
  const { busy, run } = useAction();
  const blank = { name: "", address_line1: "", city: "", state: "", pincode: "", is_primary: false };
  const [f, setF] = useState(blank);
  const [adding, setAdding] = useState(false);
  return (
    <div className="section stack">
      <div className="row between">
        <h2>Sites</h2>
        {canWrite && !adding && (
          <button className="btn" onClick={() => setAdding(true)}>
            Add site
          </button>
        )}
      </div>
      {adding && (
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await run(() => post(`/customers/${customerId}/sites`, f), "Site added");
            if (r !== undefined) {
              setF(blank);
              setAdding(false);
              void list.reload();
            }
          }}
        >
          <div className="form-grid">
            <Field id="st-name" label="Site name">
              <input id="st-name" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            </Field>
            <Field id="st-a1" label="Address">
              <input id="st-a1" required value={f.address_line1} onChange={(e) => setF({ ...f, address_line1: e.target.value })} />
            </Field>
            <Field id="st-city" label="City">
              <input id="st-city" required value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} />
            </Field>
            <Field id="st-state" label="State">
              <input id="st-state" required value={f.state} onChange={(e) => setF({ ...f, state: e.target.value })} />
            </Field>
            <Field id="st-pin" label="PIN code">
              <input
                id="st-pin"
                required
                inputMode="numeric"
                maxLength={6}
                value={f.pincode}
                onChange={(e) => setF({ ...f, pincode: e.target.value.replace(/\D/g, "") })}
              />
            </Field>
          </div>
          <Check checked={f.is_primary} onChange={(v) => setF({ ...f, is_primary: v })}>
            Main site
          </Check>
          <div className="row">
            <button className="btn primary" disabled={busy || !f.name || !f.address_line1 || !/^\d{6}$/.test(f.pincode)}>
              Save site
            </button>
            <button type="button" className="btn quiet" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {!list.data ? (
        <Skeleton lines={2} />
      ) : list.data.length === 0 ? (
        <p className="muted">No sites yet. The customer's address is used.</p>
      ) : (
        <ul className="plain-list">
          {list.data.map((s) => (
            <li key={s.id}>
              <strong>{s.name}</strong> {s.is_primary && <Badge>Main</Badge>}
              <div className="muted small">
                {s.city}, {s.state} {s.pincode}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function CustomerPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useMe();
  const c = useData<S["CustomerOut"]>(`/customers/${id}`);
  const projects = useData<Page<S["ProjectOut"]>>(`/projects?customer_id=${id}&size=50`);
  const [editing, setEditing] = useState(false);
  const { run } = useAction();
  if (c.error) return <Notice tone="bad">{c.error}</Notice>;
  if (!c.data) return <Skeleton lines={8} />;
  const cust = c.data;
  const canWrite = can("customer:write");
  return (
    <div>
      <Back href="/customers" label="Customers" />
      <div className="page-head">
        <div>
          <h1>{cust.display_name}</h1>
          <p>
            <span className="mono">{cust.code}</span>, {cust.legal_name}. {cust.city}, {cust.state} {cust.pincode}
          </p>
        </div>
        <div className="row">
          {canWrite && !editing && (
            <button className="btn" onClick={() => setEditing(true)}>
              Edit details
            </button>
          )}
          {can("customer:delete") && (
            <ConfirmButton
              question="Delete this customer? It can be restored."
              confirmLabel="Delete"
              onConfirm={async () => {
                const r = await run(() => del(`/customers/${id}`), "Customer deleted");
                if (r !== undefined) router.push("/customers");
              }}
            >
              Delete
            </ConfirmButton>
          )}
        </div>
      </div>
      {editing && (
        <CustomerForm
          edit
          initial={cust}
          submitLabel="Save changes"
          onCancel={() => setEditing(false)}
          onSubmit={async (body) => {
            await patch(`/customers/${id}`, { ...body, version: cust.version });
            setEditing(false);
            void c.reload();
          }}
        />
      )}
      <div className="section">
        <dl className="kv">
          <dt>GSTIN</dt>
          <dd className="mono">{cust.gstin ?? "Not given"}</dd>
          <dt>Size</dt>
          <dd>{cust.segment}</dd>
          <dt>Industry</dt>
          <dd>{cust.industry ?? "Not given"}</dd>
          <dt>Employees</dt>
          <dd>{cust.employee_count ?? "Not given"}</dd>
        </dl>
        {cust.notes && <p className="small" style={{ marginTop: 8 }}>{cust.notes}</p>}
      </div>
      <div className="section stack">
        <h2>Projects</h2>
        {!projects.data ? (
          <Skeleton lines={2} />
        ) : projects.data.items.length === 0 ? (
          <Empty title="No projects yet">Start one from the Projects page.</Empty>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Project</th>
                <th>Stage</th>
                <th className="right">Started</th>
              </tr>
            </thead>
            <tbody>
              {projects.data.items.map((p) => (
                <tr key={p.id}>
                  <td data-label="Project">
                    <Link href={`/projects/${p.id}`}>{p.name}</Link>
                    <div className="muted small mono">{p.code}</div>
                  </td>
                  <td data-label="Stage">{stageName(p.current_stage)}</td>
                  <td data-label="Started" className="right">
                    {date(p.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <Sites customerId={id} canWrite={canWrite} />
      <Contacts customerId={id} canWrite={canWrite} />
    </div>
  );
}
