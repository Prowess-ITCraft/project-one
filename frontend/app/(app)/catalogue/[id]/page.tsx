"use client";
import { Back } from "@/components/kit";
import { useParams } from "next/navigation";
import { useState } from "react";
import { dateTime, date, money, post, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Field, Notice, Skeleton, priceTone, priceWords, useAction } from "@/components/ui";

function todayIso(offset = 0) {
  const d = new Date(Date.now() + offset * 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

function PriceForm({ id, onDone }: { id: string; onDone: () => void }) {
  const { busy, run } = useAction();
  const [f, setF] = useState({
    supplier: "",
    cost: "",
    selling: "",
    quoted_on: todayIso(),
    valid_until: todayIso(5),
    source_note: "",
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const below = f.cost !== "" && f.selling !== "" && Number(f.selling) < Number(f.cost);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    const r = await run(() => post(`/catalogue/items/${id}/prices`, f, { idem: true }), "Price saved");
    if (r !== undefined) onDone();
  }

  return (
    <form onSubmit={submit} className="stack" style={{ maxWidth: 640 }}>
      <div className="grid2">
        <Field id="supplier" label="Supplier">
          <input id="supplier" type="text" required value={f.supplier} onChange={set("supplier")} />
        </Field>
        <Field id="src" label="Where the price came from" hint="For example: email quote from the distributor">
          <input id="src" type="text" required minLength={3} value={f.source_note} onChange={set("source_note")} />
        </Field>
        <Field id="cost" label="Cost price (INR)">
          <input id="cost" type="text" inputMode="decimal" required pattern="[0-9]+(\.[0-9]{1,2})?" value={f.cost} onChange={set("cost")} />
        </Field>
        <Field id="sell" label="Selling price (INR)" error={below ? "Selling price is below cost. Check both amounts." : undefined}>
          <input id="sell" type="text" inputMode="decimal" required pattern="[0-9]+(\.[0-9]{1,2})?" value={f.selling} onChange={set("selling")} />
        </Field>
        <Field id="q" label="Quoted on">
          <input id="q" type="date" required value={f.quoted_on} onChange={set("quoted_on")} />
        </Field>
        <Field id="v" label="Valid until">
          <input id="v" type="date" required value={f.valid_until} onChange={set("valid_until")} />
        </Field>
      </div>
      <div>
        <button className="btn primary" disabled={busy || below}>
          {busy ? "Saving" : "Save price"}
        </button>
      </div>
    </form>
  );
}

export default function Item() {
  const { id } = useParams<{ id: string }>();
  const { can } = useMe();
  const item = useData<S["ItemOut"]>(`/catalogue/items/${id}`);
  const seesPrices = can("price:read");
  const price = useData<S["PriceStateOut"]>(seesPrices ? `/catalogue/items/${id}/price` : null);
  const history = useData<S["PriceOut"][]>(seesPrices ? `/catalogue/items/${id}/prices` : null);
  const [adding, setAdding] = useState(false);

  if (item.error) return <Notice tone="bad">{item.error}</Notice>;
  if (!item.data) return <Skeleton lines={8} />;
  const i = item.data;
  const cur = price.data;

  return (
    <>
      <div className="page-head">
        <div>
          <Back href="/catalogue" label="Catalogue" />
          <h1>{i.name}</h1>
          <p className="mono">{i.code}</p>
        </div>
        {seesPrices && cur && <Badge tone={priceTone(cur.state)}>{cur.state === "missing" ? "No price" : priceWords(cur.state, cur.days_left)}</Badge>}
      </div>

      {i.description && <p style={{ maxWidth: "62ch", marginBottom: 20 }}>{i.description}</p>}

      <dl className="kv" style={{ marginBottom: 8 }}>
        <dt>Kind</dt>
        <dd>{i.kind === "product" ? "Product" : "Service"}</dd>
        <dt>Unit</dt>
        <dd>{i.uom}</dd>
        <dt>GST</dt>
        <dd className="num">{i.gst_rate}%</dd>
        <dt>Stock</dt>
        <dd>{i.stock_status.replace("_", " ")}</dd>
        {i.eol_date && (
          <>
            <dt>End of life</dt>
            <dd>{date(i.eol_date)}</dd>
          </>
        )}
        {i.eos_date && (
          <>
            <dt>End of support</dt>
            <dd>{date(i.eos_date)}</dd>
          </>
        )}
      </dl>

      {i.inclusions.length > 0 && (
        <div className="section">
          <h2>What is included</h2>
          <ul style={{ margin: "8px 0 0", paddingLeft: 20, maxWidth: "70ch" }}>
            {i.inclusions.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {seesPrices && (
        <div className="section">
          <div className="row between">
            <h2>Price</h2>
            {can("price:write") && !adding && (
              <button className="btn primary" onClick={() => setAdding(true)}>
                {cur?.price ? "Enter a new price" : "Enter a price"}
              </button>
            )}
          </div>
          {cur?.price ? (
            <dl className="kv" style={{ margin: "12px 0" }}>
              <dt>Selling price</dt>
              <dd className="num">{money(cur.price.selling)}</dd>
              <dt>Cost price</dt>
              <dd className="num">{money(cur.price.cost)}</dd>
              <dt>Margin</dt>
              <dd className="num">{cur.price.margin_percent ? `${cur.price.margin_percent}%` : "Not available"}</dd>
              <dt>Valid until</dt>
              <dd>{date(cur.price.valid_until)}</dd>
              <dt>Source</dt>
              <dd>
                {cur.price.supplier}, {cur.price.source_note}
              </dd>
            </dl>
          ) : (
            <p className="lede">No price has been entered. A quotation cannot use this item until one is.</p>
          )}
          {adding && (
            <PriceForm
              id={id}
              onDone={() => {
                setAdding(false);
                price.reload();
                history.reload();
              }}
            />
          )}
        </div>
      )}

      {seesPrices && history.data && history.data.length > 1 && (
        <div className="section">
          <h2>Price history</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Entered</th>
                <th className="right">Selling</th>
                <th>Supplier</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {history.data.map((h) => (
                <tr key={h.id}>
                  <td data-label="Entered">{dateTime(h.created_at)}</td>
                  <td data-label="Selling" className="num">
                    {money(h.selling)}
                  </td>
                  <td data-label="Supplier">{h.supplier}</td>
                  <td data-label="Status">
                    <Badge tone={h.status === "active" ? "ok" : undefined}>{h.status}</Badge>
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
