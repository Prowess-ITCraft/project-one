import type { Page } from "@playwright/test";
import { expect, settle, signIn, signInAs, test, who } from "./support";

/** What the browser holds 15 minutes after sign-in: the short cookie is gone, the 14-day one stays. */
async function dropShortCookie(page: Page) {
  const ctx = page.context();
  const keep = (await ctx.cookies()).filter((c) => c.name !== "p1_access");
  await ctx.clearCookies();
  await ctx.addCookies(keep);
}

async function projectWith(page: Page, match: (p: { status: string; current_stage: string }) => boolean) {
  const r = await page.request.get("/api/v1/projects?size=100");
  const body = await r.json();
  return ((body.items ?? body) as { id: string; status: string; current_stage: string }[]).find(match);
}

test("a document download renews the sign-in first", async ({ page, problems }) => {
  await signIn(page, "director");
  const done = await projectWith(page, (p) => p.status === "completed");
  test.skip(!done, "no completed demo project");
  await page.goto(`/projects/${done!.id}#completion`);
  await settle(page);
  await dropShortCookie(page);
  // The browser fetches a download itself; without the renewal this answered 401.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download PDF" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  void problems;
});

test("signing in again returns to the page you were on", async ({ page, problems }) => {
  const person = await signIn(page, "director");
  const live = await projectWith(page, (p) => p.current_stage === "field_work");
  test.skip(!live, "no project in field work");
  // The whole session has ended (signed out elsewhere, or 14 days passed).
  await page.context().clearCookies();
  await page.goto(`/projects/${live!.id}#field`);
  await page.waitForURL((u) => u.pathname === "/login");
  expect(new URL(page.url()).searchParams.get("next")).toBe(`/projects/${live!.id}#field`);
  await signInAs(page, who(person.roles[0]), { here: true });
  await page.waitForURL((u) => u.pathname === `/projects/${live!.id}`);
  await settle(page);
  await expect(page.getByRole("heading", { name: "Field work" })).toBeVisible();
  void problems;
});

test("the sign-in page ignores a next address outside the app", async ({ page, problems }) => {
  await signIn(page, "sales_manager");
  await page.goto("/login?next=//example.com/");
  await page.waitForURL((u) => u.pathname === "/projects");
  expect(new URL(page.url()).host).toBe(new URL(test.info().project.use.baseURL!).host);
  void problems;
});
