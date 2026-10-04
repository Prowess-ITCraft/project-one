import path from "node:path";
import { request, type APIRequestContext } from "@playwright/test";
import { accounts, expect, settle, signIn, test, totp, who } from "./support";

/**
 * The main job of the tool: a PrismSuite report in, a priced BOQ estimate out, in one step
 * (ADR 0024). Creates one project for Shakti, so run it on a dev stack with the demo data.
 */
const REPORT = path.resolve(__dirname, "../../samples/Shakti Equipments Pvt. Ltd. PrismSuite Audit Report.docx");
let projectId = "";

async function api(role: string): Promise<APIRequestContext> {
  const a = who(role);
  const ctx = await request.newContext({ baseURL: test.info().project.use.baseURL });
  let body = await (await ctx.post("/api/v1/auth/login", { data: { email: a.email, password: accounts.password } })).json();
  if (body.status === "mfa_required") {
    body = await (await ctx.post("/api/v1/auth/mfa/verify", { data: { challenge_token: body.challenge_token, code: totp(a.totp_secret!) } })).json();
  }
  return request.newContext({ baseURL: test.info().project.use.baseURL, extraHTTPHeaders: { Authorization: `Bearer ${body.access_token}` } });
}

test.describe.serial("Report to BOQ in one step", () => {
  test.beforeAll(async () => {
    const head = await api("sales_head");
    const found = await (await head.get("/api/v1/customers", { params: { q: "Shakti" } })).json();
    const customer = (found.items ?? found)[0];
    const proj = await (
      await head.post("/api/v1/projects", {
        data: { customer_id: customer.id, name: `One-step BOQ check ${Date.now().toString(36)}` },
        headers: { "Idempotency-Key": crypto.randomUUID().replace(/-/g, "") },
      })
    ).json();
    projectId = proj.id;
    for (const [role, projectRole] of [["sales_manager", "sales_manager"], ["audit_engineer", "audit_engineer"]]) {
      const me = await (await (await api(role)).get("/api/v1/auth/me")).json();
      const r = await head.put(`/api/v1/projects/${projectId}/members`, { data: { user_id: me.id, project_role: projectRole } });
      expect(r.ok(), await r.text()).toBeTruthy();
    }
  });

  test("sales uploads the report and gets a priced estimate", async ({ page, problems }) => {
    await signIn(page, "sales_manager");
    await page.goto(`/projects/${projectId}`);
    await settle(page);
    await page.getByRole("button", { name: "Upload report and draft BOQ" }).click();
    await page.locator("#qb-file").setInputFiles(REPORT);
    await page.locator("#qb-un").fill("27");
    await page.locator("#qb-u12").fill("35");
    await page.getByRole("button", { name: "Upload and draft BOQ" }).click();
    await expect(page.getByRole("heading", { name: /BOQ estimate/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/Sophos XGS-108/).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /PDF/ }).first()).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("the audit engineer reuses the imported report", async ({ page, problems }) => {
    await signIn(page, "audit_engineer");
    await page.goto(`/projects/${projectId}`);
    await settle(page);
    await page.getByRole("button", { name: "Upload report and draft BOQ" }).click();
    await expect(page.getByText(/Leave empty to use revision 1/)).toBeVisible();
    await expect(page.locator("#qb-un")).toHaveValue("27");
    await page.getByRole("button", { name: "Upload and draft BOQ" }).click();
    await expect(page.getByRole("heading", { name: /BOQ estimate/ })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/Sophos XGS-108/).first()).toBeVisible();
    expect(problems).toEqual([]);
  });
});

test("a signed-in person is not asked for the code again when the short cookie runs out", async ({ page, problems }) => {
  await signIn(page, "sales_manager");
  // What the browser does 15 minutes after sign-in: the short cookie is gone, the 14-day one stays.
  const ctx = page.context();
  const keep = (await ctx.cookies()).filter((c) => c.name !== "p1_access");
  await ctx.clearCookies();
  await ctx.addCookies(keep);
  await page.goto("/projects");
  await expect(page.locator("nav.nav a").first()).toBeVisible();
  await expect(page.getByText("We could not load your account")).toHaveCount(0);
  // The sign-in page sends someone already signed in straight back into the app.
  await page.goto("/login");
  await page.waitForURL((u) => u.pathname === "/projects");
  expect(problems).toEqual([]);
});
