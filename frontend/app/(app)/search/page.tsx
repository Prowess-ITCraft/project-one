"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import type { S } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { Empty, Notice, Skeleton } from "@/components/ui";

const KINDS: { id: string; label: string }[] = [
  { id: "", label: "Everything" },
  { id: "customer", label: "Customers" },
  { id: "project", label: "Projects" },
  { id: "quote", label: "Quotes" },
  { id: "task", label: "Field tasks" },
  { id: "item", label: "Catalogue" },
];

function Results() {
  const params = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(params.get("q") ?? "");
  const kind = params.get("kind") ?? "";
  const query = (params.get("q") ?? "").trim();
  useEffect(() => setQ(params.get("q") ?? ""), [params]);
  const hits = useData<S["SearchHitOut"][]>(
    query.length >= 2 ? `/search?q=${encodeURIComponent(query)}&limit=30${kind ? `&kind=${kind}` : ""}` : null,
  );
  const go = (next: string, k = kind) => router.replace(`/search?q=${encodeURIComponent(next)}${k ? `&kind=${k}` : ""}`);
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Search</h1>
          <p>Customers, projects, quotes, field tasks and catalogue items you can open. Prices are never searched.</p>
        </div>
      </div>
      <form
        className="row"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          go(q.trim());
        }}
      >
        <input type="search" aria-label="Search for" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <button className="btn primary">Search</button>
      </form>
      <div className="row" role="group" aria-label="What to search" style={{ margin: "12px 0" }}>
        {KINDS.map((k) => (
          <button key={k.id} className={`btn small${k.id === kind ? " primary" : " quiet"}`} onClick={() => go(query, k.id)}>
            {k.label}
          </button>
        ))}
      </div>
      {query.length < 2 && <p className="muted">Type at least two letters: a name, a code or part of a quote number.</p>}
      {hits.error && <Notice tone="bad">{hits.error}</Notice>}
      {hits.loading && !hits.data && <Skeleton lines={5} />}
      {hits.data && hits.data.length === 0 && <Empty title="Nothing found">Try fewer words, or part of a code such as 030.</Empty>}
      {hits.data && hits.data.length > 0 && (
        <ul className="inbox">
          {hits.data.map((h) => (
            <li key={h.url + h.title}>
              <span className="subject">
                <Link href={h.url}>{h.title}</Link>
              </span>
              <span className="muted small">{KINDS.find((k) => k.id === h.kind)?.label ?? h.kind}</span>
              {h.subtitle && <span className="body">{h.subtitle}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<Skeleton lines={4} />}>
      <Results />
    </Suspense>
  );
}
