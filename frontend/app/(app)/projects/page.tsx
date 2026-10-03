"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { post, type S } from "@/lib/api";
import { date } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Field, Notice, Skeleton, stageName, useAction } from "@/components/ui";

type Page<T> = { items: T[]; total: number };

function NewProject({ customers, onDone }: { customers: S["CustomerOut"][]; onDone: () => void }) {
  const router = useRouter();
  const { busy, run } = useAction();
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? "");
  const [name, setName] = useState("");
  const [addCustomer, setAddCustomer] = useState(customers.length === 0);
  const [c, setC] = useState({ legal_name: "", address_line1: "", city: "", state: "", pincode: "" });
  const [error, setError] = useState("");

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError("");
    const r = await run(async () => {
      let cid = customerId;
      if (addCustomer) {
        const cust = await post<S["CustomerOut"]>("/customers", c);
        cid = cust.id;
      }
      return post<S["ProjectOut"]>("/projects", { customer_id: cid, name }, { idem: true });
    }, "Project created");
    if (r) {
      onDone();
      router.push(`/projects/${r.id}`);
    }
  }

  return (
    <form className="section" onSubmit={submit}>
      <h2>New project</h2>
      <p className="lede">A project follows one customer from audit to certificate.</p>
      <div className="grid2">
        <Field id="pname" label="Project name" hint="For example: IT infrastructure hardening">
          <input id="pname" type="text" required minLength={3} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        {!addCustomer && (
          <Field id="cust" label="Customer">
            <select id="cust" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              {customers.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.display_name}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
      {addCustomer && (
        <div className="stack" style={{ marginBottom: 12 }}>
          <h3>Customer details</h3>
          <div className="grid2">
            <Field id="ln" label="Legal name">
              <input id="ln" type="text" required value={c.legal_name} onChange={(e) => setC({ ...c, legal_name: e.target.value })} />
            </Field>
            <Field id="a1" label="Address">
              <input id="a1" type="text" required value={c.address_line1} onChange={(e) => setC({ ...c, address_line1: e.target.value })} />
            </Field>
            <Field id="city" label="City">
              <input id="city" type="text" required value={c.city} onChange={(e) => setC({ ...c, city: e.target.value })} />
            </Field>
            <Field id="state" label="State">
              <input id="state" type="text" required value={c.state} onChange={(e) => setC({ ...c, state: e.target.value })} />
            </Field>
            <Field id="pin" label="PIN code" hint="6 digits">
              <input id="pin" type="text" inputMode="numeric" required pattern="[1-9][0-9]{5}" value={c.pincode} onChange={(e) => setC({ ...c, pincode: e.target.value })} />
            </Field>
          </div>
        </div>
      )}
      {error && <Notice tone="bad">{error}</Notice>}
      <div className="row">
        <button className="btn primary" disabled={busy || !name}>
          {busy ? "Creating" : "Create project"}
        </button>
        {customers.length > 0 && (
          <button type="button" className="btn quiet" onClick={() => setAddCustomer(!addCustomer)}>
            {addCustomer ? "Use an existing customer" : "Add a new customer"}
          </button>
        )}
      </div>
    </form>
  );
}

export default function Projects() {
  const { can } = useMe();
  const projects = useData<Page<S["ProjectOut"]>>("/projects?size=100");
  const customers = useData<Page<S["CustomerOut"]>>("/customers?size=200");
  const [creating, setCreating] = useState(false);
  const name = new Map((customers.data?.items ?? []).map((c) => [c.id, c.display_name]));
  const canCreate = can("project:write") && can("customer:write");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Projects</h1>
          <p>Every project, and the stage it is at.</p>
        </div>
        {canCreate && !creating && (
          <button className="btn primary" onClick={() => setCreating(true)}>
            New project
          </button>
        )}
      </div>

      {creating && customers.data && (
        <NewProject
          customers={customers.data.items}
          onDone={() => {
            setCreating(false);
            projects.reload();
          }}
        />
      )}

      {projects.loading && !projects.data && <Skeleton lines={6} />}
      {projects.error && <Notice tone="bad">{projects.error}</Notice>}
      {projects.data && projects.data.items.length === 0 && (
        <Empty
          title="No projects yet"
          action={
            canCreate ? (
              <button className="btn primary" onClick={() => setCreating(true)}>
                Create the first project
              </button>
            ) : undefined
          }
        >
          {canCreate
            ? "Create a project to start with a customer's audit report."
            : "Projects you are added to will appear here. Ask a project manager to add you."}
        </Empty>
      )}
      {projects.data && projects.data.items.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Project</th>
              <th>Customer</th>
              <th>Stage</th>
              <th>Status</th>
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
                <td data-label="Customer">{name.get(p.customer_id) ?? ""}</td>
                <td data-label="Stage">{stageName(p.current_stage)}</td>
                <td data-label="Status">
                  <Badge tone={p.status === "active" ? "accent" : p.status === "completed" ? "ok" : undefined}>
                    {p.status.replace("_", " ")}
                  </Badge>
                </td>
                <td data-label="Started" className="right">
                  {date(p.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
