import { expect, settle, test, totp } from "./support";

/**
 * The accounts panel, as the development admin (`python -m app.cli seed-demo`, which also clears
 * its authenticator so this test can set one up). Creates one account, so run it on a dev stack.
 */
const ADMIN = { email: "adi@test.com", password: "test1234" };

test.describe("Admin", () => {
  test("create an account with two roles, change its roles, deactivate it", async ({ page, problems }) => {
    await page.goto("/login");
    await page.locator("#email").fill(ADMIN.email);
    await page.locator("#password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("button", { name: "Show my code" }).click();
    const secret = (await page.locator(".enrol-key").innerText()).replace(/\s+/g, "");
    await page.locator("#code").fill(totp(secret));
    await page.getByRole("button", { name: "Confirm and continue" }).click();
    await page.getByRole("button", { name: "I saved them, continue" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"));

    await page.locator("nav.nav").getByRole("link", { name: "Accounts" }).click();
    await expect(page.getByRole("heading", { name: "Accounts" })).toBeVisible();
    await expect(page.getByRole("tab", { name: /Everyone/ })).toBeVisible();

    const stamp = Date.now().toString(36);
    const email = `check.${stamp}@example.com`;
    await page.getByRole("button", { name: "New account" }).click();
    await page.locator("#n").fill("Panel Check");
    await expect(page.locator("#i")).toHaveValue("PC");
    await page.locator("#e").fill(email);
    await page.locator("#d").fill("Checks the accounts panel");
    await page.getByRole("checkbox", { name: /^Project manager/ }).check();
    await page.getByRole("checkbox", { name: /^Field engineer/ }).check();
    const password = await page.locator("#p").inputValue();
    expect(password.length).toBeGreaterThanOrEqual(12);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.locator(".secret")).toHaveText(password);
    await page.getByRole("button", { name: "Done" }).click();

    // listed under both roles, and searchable
    await page.getByRole("tab", { name: /Field engineer/ }).click();
    await page.getByRole("searchbox", { name: "Search accounts" }).fill(stamp);
    const row = page.locator("tr", { hasText: email });
    await expect(row).toContainText("Project manager, Field engineer");

    // change roles, then deactivate
    await row.getByRole("button", { name: "Panel Check" }).click();
    const drawer = page.getByRole("dialog", { name: "Panel Check" });
    await drawer.getByRole("checkbox", { name: /^Field engineer/ }).uncheck();
    await drawer.getByRole("checkbox", { name: /^Technical lead/ }).check();
    await drawer.getByRole("button", { name: "Save roles" }).click();
    await settle(page);
    await drawer.getByRole("button", { name: "Deactivate account" }).click();
    await drawer.getByRole("button", { name: "Deactivate", exact: true }).click();
    await expect(drawer.getByText("Deactivated")).toBeVisible();
    await drawer.getByRole("button", { name: "Close" }).click();

    await page.getByRole("tab", { name: /Deactivated/ }).click();
    await expect(page.locator("tr", { hasText: email })).toContainText("Project manager, Technical lead / verifier");

    // a deactivated account cannot sign in
    const r = await page.request.post("/api/v1/auth/login", { data: { email, password } });
    expect([401, 403]).toContain(r.status());
    expect(problems).toEqual([]);
  });
});
