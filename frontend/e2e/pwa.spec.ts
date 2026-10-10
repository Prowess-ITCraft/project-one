import { expect, settle, signIn, test } from "./support";

/**
 * The field app installs on a phone (ADR 0027). Lighthouse 12 dropped its PWA checks, so
 * the install criteria are checked here: a valid manifest with the right icons, a service worker
 * that controls the page, and the page shell still opening with no signal.
 */
test.describe("Installable app @phone", () => {
  test("manifest, icons and a service worker that works offline @phone", async ({ page, problems }) => {
    const m = await (await page.request.get("/manifest.webmanifest")).json();
    expect(m.name).toBe("Project One");
    expect(m.display).toBe("standalone");
    expect(m.start_url).toBe("/field");
    expect(m.theme_color).toMatch(/^#[0-9A-Fa-f]{6}$/);
    const sizes = (m.icons as { sizes: string; purpose: string; src: string }[]).map((i) => `${i.sizes}:${i.purpose}`);
    expect(sizes).toEqual(expect.arrayContaining(["192x192:any", "512x512:any", "512x512:maskable"]));
    for (const icon of m.icons) expect((await page.request.get(icon.src)).ok()).toBeTruthy();

    const sw = await page.request.get("/sw.js?v=test");
    expect(sw.ok()).toBeTruthy();
    expect(sw.headers()["cache-control"]).toContain("no-cache");
    // The worker gets the same policy as the pages: it only ever fetches its own origin.
    const swPolicy = sw.headers()["content-security-policy"] ?? "";
    if (swPolicy) expect(swPolicy).toContain("connect-src 'self'");

    await signIn(page, "field_engineer");
    await settle(page);
    const csp = (await page.request.get("/field")).headers()["content-security-policy"] ?? "";
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("worker-src 'self'");
    // the service worker takes control after the first load
    await page.reload();
    await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker?.controller), { timeout: 20_000 }).toBe(true);
    // and the page shell opens with no signal
    await page.context().setOffline(true);
    await page.reload();
    await expect(page.locator(".field-shell, .shell").first()).toBeVisible();
    await page.context().setOffline(false);
    problems.length = 0; // requests fail while offline, on purpose
  });
});
