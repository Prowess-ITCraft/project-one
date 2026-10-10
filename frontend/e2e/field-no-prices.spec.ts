import { expect, settle, signIn, test } from "./support";

/**
 * ADR 0003: no price field ever reaches the Field engineer role. Every answer the browser gets
 * while a field engineer uses the app is read, and none may carry a price, a cost, an amount, a
 * margin or a rupee sign. The backend has the same check over every route
 * (tests/test_field_role_never_sees_prices.py); this one watches the real traffic.
 */
const MONEY = /(^|_)(price|prices|selling|cost|costs|amount|amounts|margin|subtotal|totals|gst)($|_)|unit_price|hint_price/i;
const NOT_MONEY = /(_rate|_minutes|_hours|_days|_count)$/;

function moneyKeys(value: unknown, path = ""): string[] {
  if (Array.isArray(value)) return value.slice(0, 50).flatMap((v, i) => moneyKeys(v, `${path}[${i}]`));
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) => [
      ...(MONEY.test(k) && !NOT_MONEY.test(k) && v !== null && !(Array.isArray(v) && !v.length) ? [`${path}.${k}`] : []),
      ...moneyKeys(v, `${path}.${k}`),
    ]);
  }
  return typeof value === "string" && value.includes("₹") ? [`${path} (rupee sign)`] : [];
}

test.describe("Field engineer @phone", () => {
  test("no answer to a field engineer carries a price @phone", async ({ page, problems }) => {
    const leaks: string[] = [];
    const seen: string[] = [];
    page.on("response", async (r) => {
      const url = new URL(r.url());
      if (!url.pathname.startsWith("/api/") || !(r.headers()["content-type"] ?? "").includes("json")) return;
      try {
        const hits = moneyKeys(await r.json());
        seen.push(url.pathname);
        if (hits.length) leaks.push(`${url.pathname}: ${hits.slice(0, 3).join(", ")}`);
      } catch {
        /* an empty or unreadable body */
      }
    });
    await signIn(page, "field_engineer");
    await expect(page).toHaveURL(/\/field/);
    await settle(page);
    const task = page.locator('a[href^="/field/"]').first();
    if (await task.count()) {
      await task.click();
      await settle(page);
    }
    for (const url of ["/notifications", "/account", "/search?q=firewall", "/help", "/field"]) {
      await page.goto(url);
      await settle(page);
    }
    // a field engineer stays in the field app: an office page sends them back to their tasks
    await page.goto("/catalogue");
    await expect(page).toHaveURL(/\/field/);
    await expect(page.locator("body")).not.toContainText(/₹/);
    expect(seen.length).toBeGreaterThan(5);
    expect(leaks, "prices reached a field engineer").toEqual([]);
    void problems;
  });
});
