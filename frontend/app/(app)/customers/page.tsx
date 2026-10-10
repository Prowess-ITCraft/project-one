"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton } from "@/components/ui";
import { CustomerForm } from "@/components/customers";

type Page<T> = { items: T[]; total: number };

export default function Customers() {
  const { can } = useMe();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const list = useData<Page<S["CustomerOut"]>>(`/customers?size=100${query ? `&q=${encodeURIComponent(query)}` : ""}`);
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Customers</h1>
          <p>The companies we audit and work for, with their sites and contacts.</p>
        </div>
        {can("customer:write") && !creating && (
          <button className="btn primary" onClick={() => setCreating(true)}>
            New customer
          </button>
        )}
      </div>
      {creating && (
        <CustomerForm
          submitLabel="Add customer"
          onCancel={() => setCreating(false)}
          onSubmit={async (body) => {
            const c = await post<S["CustomerOut"]>("/customers", body);
            router.push(`/customers/${c.id}`);
          }}
        />
      )}
      <div className="field task-filter">
        <label htmlFor="cust-q">Find a customer</label>
        <input id="cust-q" type="search" value={q} placeholder="Name, code or GSTIN" onChange={(e) => setQ(e.target.value)} />
      </div>
      {list.error && <Notice tone="bad">{list.error}</Notice>}
      {list.loading && !list.data && <Skeleton lines={6} />}
      {list.data && list.data.items.length === 0 && (
        <Empty title={query ? "No customer matches" : "No customers yet"}>
          {query ? "Try part of the name or the customer code." : "Add the first customer to start a project."}
        </Empty>
      )}
      {list.data && list.data.items.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Customer</th>
              <th>City</th>
              <th>Size</th>
              <th>GSTIN</th>
            </tr>
          </thead>
          <tbody>
            {list.data.items.map((c) => (
              <tr key={c.id}>
                <td data-label="Customer">
                  <Link href={`/customers/${c.id}`}>{c.display_name}</Link>
                  <div className="muted small mono">{c.code}</div>
                </td>
                <td data-label="City">
                  {c.city}, {c.state}
                </td>
                <td data-label="Size">
                  <Badge>{c.segment}</Badge>
                </td>
                <td data-label="GSTIN" className="mono">
                  {c.gstin ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.data && list.data.total > list.data.items.length && (
        <p className="muted small">
          Showing {list.data.items.length} of {list.data.total}. Search to narrow the list.
        </p>
      )}
    </div>
  );
}
