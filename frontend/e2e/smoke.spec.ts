import type { Page } from "@playwright/test";
import { accounts, expect, expectFailure, settle, signIn, test, visit } from "./support";

type Project = { id: string; code: string; name: string; current_stage: string; status: string };

async function projects(page: Page): Promise<Project[]> {
  const r = await page.request.get("/api/v1/projects?size=100");
  expect(r.ok()).toBeTruthy();
  const body = await r.json();
  return (body.items ?? body) as Project[];
}

/** Click through every tab of a project and screenshot each. */
async function everyTab(page: Page, p: Project, prefix: string) {
  // "not created yet" answers 404 by design; the tab shows its empty state
  expectFailure(page, /\/projects\/[^/]+\/(gaps|boq)$/);
  await visit(page, `/projects/${p.id}`, `${prefix}-${p.code}-overview`);
  const tabs = page.getByRole("tab");
  const names = await tabs.allInnerTexts();
  for (const name of names) {
    await page.getByRole("tab", { name, exact: true }).click();
    await settle(page);
    const bad = await page.locator(".notice.bad").allInnerTexts();
    expect(bad, `${p.code} tab ${name}`).toEqual([]);
    await page.screenshot({ path: `e2e/screens/${prefix}-${p.code}-${name.toLowerCase().replace(/\W+/g, "-")}.png`, fullPage: true });
  }
}

/** Every link in the side navigation opens without errors. */
async function everyNavPage(page: Page, prefix: string) {
  const links = await page.locator("nav.nav a").evaluateAll((as) => as.map((a) => (a as HTMLAnchorElement).getAttribute("href")!));
  for (const href of links) await visit(page, href, `${prefix}-nav${href.replace(/\//g, "-")}`);
  return links;
}

test.describe("Director", () => {
  test("dashboard, every page and the finished project", async ({ page, problems }) => {
    await signIn(page, "director");
    const links = await everyNavPage(page, "director");
    expect(links).toContain("/dashboard");
    await visit(page, "/dashboard", "director-dashboard");
    await expect(page.locator(".figures")).toBeVisible();
    for (const p of await projects(page)) await everyTab(page, p, "director");
    void problems;
  });

  test("the certificate of the finished project is valid and downloadable", async ({ page, problems }) => {
    await signIn(page, "director");
    const done = (await projects(page)).find((p) => p.status === "completed");
    test.skip(!done, "no completed demo project");
    await page.goto(`/projects/${done!.id}#completion`);
    await settle(page);
    await expect(page.locator(".ledger li[data-met='false']")).toHaveCount(0);
    await expect(page.locator(".certline")).toContainText("IITPL-");
    const pdf = await page.request.get(await page.getByRole("link", { name: "Download PDF" }).getAttribute("href") as string);
    expect(pdf.headers()["content-type"]).toContain("application/pdf");
    void problems;
  });
});

test.describe("Project manager", () => {
  test("projects, field work and completion", async ({ page, problems }) => {
    await signIn(page, "project_manager");
    await everyNavPage(page, "pm");
    const live = (await projects(page)).filter((p) => p.current_stage === "field_work");
    expect(live.length).toBeGreaterThan(0);
    await page.goto(`/projects/${live[0].id}#field`);
    await settle(page);
    await expect(page.getByRole("heading", { name: "Field work" })).toBeVisible();
    await page.screenshot({ path: "e2e/screens/pm-field.png", fullPage: true });
    void problems;
  });
});

test.describe("Sales", () => {
  test("projects, catalogue and the BOQ", async ({ page, problems }) => {
    await signIn(page, "sales_manager");
    await everyNavPage(page, "sales");
    const p = (await projects(page))[0];
    await page.goto(`/projects/${p.id}#boq`);
    await settle(page);
    await page.screenshot({ path: "e2e/screens/sales-boq.png", fullPage: true });
    void problems;
  });
});

test.describe("Technical lead", () => {
  test("review queue and dashboard", async ({ page, problems }) => {
    await signIn(page, "technical_lead");
    await everyNavPage(page, "lead");
    await visit(page, "/review", "lead-review");
    void problems;
  });
});

test.describe("Audit engineer", () => {
  test("projects and audit imports", async ({ page, problems }) => {
    await signIn(page, "audit_engineer");
    await everyNavPage(page, "auditor");
    const p = (await projects(page))[0];
    await page.goto(`/projects/${p.id}#audit`);
    await settle(page);
    const imp = page.locator('a[href^="/imports/"]').first();
    if (await imp.count()) {
      await imp.click();
      await settle(page);
      await page.screenshot({ path: "e2e/screens/auditor-import.png", fullPage: true });
    }
    void problems;
  });
});

test.describe("Field engineer @phone", () => {
  test("my tasks and a task, with no prices anywhere @phone", async ({ page, problems }) => {
    await signIn(page, "field_engineer");
    await expect(page).toHaveURL(/\/field/);
    await settle(page);
    await page.screenshot({ path: "e2e/screens/engineer-phone-tasks.png", fullPage: true });
    const task = page.locator('a[href^="/field/"]').first();
    await expect(task).toBeVisible();
    await task.click();
    await settle(page);
    await page.screenshot({ path: "e2e/screens/engineer-phone-task.png", fullPage: true });
    await expect(page.locator("body")).not.toContainText(/₹|price/i);
    void problems;
  });
});

test.describe("Public pages", () => {
  test("certificate check: genuine, unknown", async ({ page, problems }) => {
    test.skip(!accounts.certificate, "no certificate in the demo data");
    await visit(page, `/verify/${accounts.certificate}`, "public-verify");
    await expect(page.locator(".verdict")).toContainText(/Genuine and valid|Revoked/);
    expectFailure(page, /\/public\/certificates\/IITPL-0000-9999$/);
    await visit(page, "/verify/IITPL-0000-9999", "public-verify-unknown", { allowNotice: /./ });
    await expect(page.locator(".verdict")).toContainText("No certificate has this number");
    void problems;
  });

  test("a bad acknowledgement link says so @phone", async ({ page, problems }) => {
    expectFailure(page, /\/public\/waivers\//);
    await visit(page, "/ack/waiver/abcdefghijklmnopqrstuvwxyz0123456789", "public-waiver-bad", { allowNotice: /not valid|expired/i });
    await expect(page.locator(".notice.bad")).toContainText(/not valid|expired/i);
    void problems;
  });
});
