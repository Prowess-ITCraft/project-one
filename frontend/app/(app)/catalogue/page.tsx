"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { date, money, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton, priceTone, priceWords } from "@/components/ui";

type Page<T> = { items: T[]; total: number };
type PriceRow = { item_id: string; state: string; selling: string; valid_until: string; days_left: number | null };
type Attention = { item_id: string; code: string; name: string; state: string; valid_until: string | null; days_left: number | null };

const STOCK: Record<string, string> = { in_stock: "In stock", limited: "Limited", on_order: "On order", out_of_stock: "Out of stock" };

export default function Catalogue() {
  const { can } = useMe();
  const seesPrices = can("price:read");
  const [tab, setTab] = useState<"items" | "attention">("items");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [category, setCategory] = useState("");

  const cats = useData<S["CategoryOut"][]>("/catalogue/categories");
  const qs = new URLSearchParams({ size: "100" });
  if (q) qs.set("q", q);
  if (kind) qs.set("kind", kind);
  if (category) qs.set("category", category);
  const items = useData<Page<S["ItemOut"]>>(`/catalogue/items?${qs}`);
  const prices = useData<PriceRow[]>(seesPrices ? "/catalogue/prices/current" : null);
  const attention = useData<Attention[]>(seesPrices && tab === "attention" ? "/catalogue/prices/attention" : null);
  const byItem = useMemo(() => new Map((prices.data ?? []).map((p) => [p.item_id, p])), [prices.data]);
  const catLabel = new Map((cats.data ?? []).map((c) => [c.code, c.label]));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Catalogue</h1>
          <p>Products and services that can go on a quotation{seesPrices ? ", with their current prices" : ""}.</p>
        </div>
      </div>

      {seesPrices && (
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "items"} onClick={() => setTab("items")}>
            All items
          </button>
          <button role="tab" aria-selected={tab === "attention"} onClick={() => setTab("attention")}>
            Prices to refresh
          </button>
        </div>
      )}

      {tab === "items" && (
        <>
          <div className="filters">
            <input type="search" aria-label="Search items" placeholder="Search by name or code" value={q} onChange={(e) => setQ(e.target.value)} />
            <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">Products and services</option>
              <option value="product">Products</option>
              <option value="service">Services</option>
            </select>
            <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {(cats.data ?? []).map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          {items.loading && !items.data && <Skeleton lines={8} />}
          {items.error && <Notice tone="bad">{items.error}</Notice>}
          {items.data && items.data.items.length === 0 && (
            <Empty title="No items match">Try a shorter search or clear the filters.</Empty>
          )}
          {items.data && items.data.items.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Category</th>
                  <th>Stock</th>
                  {seesPrices && <th className="right">Selling price</th>}
                  {seesPrices && <th>Price</th>}
                </tr>
              </thead>
              <tbody>
                {items.data.items.map((i) => {
                  const p = byItem.get(i.id);
                  return (
                    <tr key={i.id}>
                      <td data-label="Item">
                        <Link href={`/catalogue/${i.id}`}>{i.name}</Link>
                        <div className="muted small mono">{i.code}</div>
                      </td>
                      <td data-label="Category">{catLabel.get(i.category) ?? i.category}</td>
                      <td data-label="Stock">
                        <Badge tone={i.stock_status === "in_stock" ? undefined : "warn"}>{STOCK[i.stock_status] ?? i.stock_status}</Badge>
                      </td>
                      {seesPrices && (
                        <td data-label="Selling price" className="num">
                          {p ? money(p.selling) : "Not set"}
                        </td>
                      )}
                      {seesPrices && (
                        <td data-label="Price">
                          <Badge tone={p ? priceTone(p.state) : "bad"}>{p ? priceWords(p.state, p.days_left) : "No price"}</Badge>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </>
      )}

      {tab === "attention" && (
        <>
          <p className="lede" style={{ marginBottom: 12 }}>
            Items whose price is missing, expired or about to expire. A quotation cannot be approved with an expired price.
          </p>
          {attention.loading && !attention.data && <Skeleton lines={6} />}
          {attention.data && attention.data.length === 0 && <Empty title="Every price is current">Nothing needs refreshing in the next 2 days.</Empty>}
          {attention.data && attention.data.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Price</th>
                  <th className="right">Valid until</th>
                </tr>
              </thead>
              <tbody>
                {attention.data.map((a) => (
                  <tr key={a.item_id}>
                    <td data-label="Item">
                      <Link href={`/catalogue/${a.item_id}`}>{a.name}</Link>
                      <div className="muted small mono">{a.code}</div>
                    </td>
                    <td data-label="Price">
                      <Badge tone={priceTone(a.state)}>{a.state === "missing" ? "No price" : priceWords(a.state, a.days_left)}</Badge>
                    </td>
                    <td data-label="Valid until" className="right">
                      {a.valid_until ? date(a.valid_until) : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </>
  );
}
