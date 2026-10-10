import type { Page } from "@playwright/test";
import { everyone, expect, settle, signInAs, test } from "./support";

/**
 * A stretch of a field task with no signal (ADR 0027): the engineer accepts
 * online, loses signal, then checks in, does the prechecks, ticks every step, adds the evidence
 * and sends it for the check, all saved on the phone. Back online, the phone sends everything in
 * order and the server applies it: the task reaches the check, the history is in the order the
 * work was done and each action keeps the time it really happened.
 */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP4z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==",
  "base64",
);
type Run = { id: string; state: string };

async function evidenceOffline(page: Page) {
  for (let n = 0; n < 20; n++) {
    const files = page.locator('input[type="file"]');
    const before = await files.count();
    if (!before) break;
    await files.first().setInputFiles({ name: "evidence.png", mimeType: "image/png", buffer: PNG });
    await expect(files).toHaveCount(before - 1);
  }
  for (let n = 0; n < 20; n++) {
    const next = page.locator('input[id^="ev-"]:visible, textarea[id^="ev-"]:visible').first();
    if (!(await next.count())) break;
    const field = page.locator(`[id="${await next.getAttribute("id")}"]`);
    await field.fill("Checked with the customer's IT contact present");
    await field.locator("xpath=ancestor::form[1]").getByRole("button", { name: "Save" }).click();
    await expect(field).toBeHidden();
  }
}

test.describe("Field engineer @phone", () => {
  test("works offline from check-in to the evidence, then syncs in order @phone", async ({ page, problems }, info) => {
    test.skip(info.project.name !== "android", "uses up a demo task; runs once, on the Android phone");
    test.setTimeout(240_000);
    await page.context().grantPermissions(["geolocation"]);
    await page.context().setGeolocation({ latitude: 19.1972, longitude: 72.9722, accuracy: 15 });

    let run: Run | undefined;
    for (const engineer of everyone("field_engineer")) {
      await page.context().clearCookies();
      await signInAs(page, engineer);
      const mine: Run[] = await (await page.request.get("/api/v1/field/my")).json();
      for (const r of mine.filter((x) => x.state === "assigned")) {
        const d = await (await page.request.get(`/api/v1/field/runs/${r.id}`)).json();
        const simple = !d.run.baseline?.length && !(d.run.evidence_reqs ?? []).some((e: { type: string }) => e.type === "config_export");
        if (!d.waiting_on?.length && simple && !d.customer_codes) {
          run = r;
          break;
        }
      }
      if (run) break;
    }
    test.skip(!run, "no simple assigned task left in the demo data: rebuild the demo");

    await page.goto(`/field/${run!.id}`);
    await settle(page);
    await page.getByRole("button", { name: "Accept task" }).click();
    await expect(page.getByRole("heading", { name: "Arrive on site" })).toBeVisible();
    await settle(page);
    // the arrival photo is always asked for (ADR 0027); wait until its picker is on the page
    await page.locator('input[type="file"]').first().waitFor({ state: "attached" });

    // no signal from here
    await page.context().setOffline(true);
    await evidenceOffline(page);
    await page.getByRole("button", { name: "Check in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Before you change anything" })).toBeVisible();
    await evidenceOffline(page);
    await page.getByRole("button", { name: "Mark prechecks done" }).click();
    await expect(page.getByRole("heading", { name: "Steps" })).toBeVisible();
    const steps = page.locator(".steps li");
    const total = await steps.count();
    for (let i = 0; i < total; i++) {
      await steps.nth(i).getByRole("button", { name: "Done" }).click();
      await expect(steps.nth(i)).toHaveAttribute("data-done", "true");
    }
    await page.getByRole("button", { name: "Mark configured" }).click();
    await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
    await evidenceOffline(page);
    await page.getByRole("button", { name: "Send for the check" }).click();

    // everything waits on the phone; the server has seen none of it
    await expect(page.locator(".sync-badge")).toContainText(/waiting, offline/);
    const waiting = Number((await page.locator(".sync-badge").innerText()).match(/(\d+) waiting/)?.[1] ?? 0);
    expect(waiting).toBeGreaterThanOrEqual(5 + total);

    // signal again: the phone sends it all, in order, and the server applies it
    await page.context().setOffline(false);
    const state = async () => (await (await page.request.get(`/api/v1/field/runs/${run!.id}`)).json()).run.state;
    await expect.poll(state, { timeout: 60_000, intervals: [1000, 2000, 3000] }).toBe("engine_check");
    await expect(page.locator(".sync-badge")).toContainText("All sent", { timeout: 30_000 });

    const detail = await (await page.request.get(`/api/v1/field/runs/${run!.id}`)).json();
    const actions: string[] = detail.events.map((e: { action: string }) => e.action);
    const order = ["accept", "check_in", "prechecks_done", "step_done", "configured", "evidence_uploaded", "engine_check"];
    const firsts = order.map((a) => actions.indexOf(a));
    expect(firsts.every((i) => i >= 0)).toBeTruthy();
    expect([...firsts].sort((a, b) => a - b)).toEqual(firsts);
    // each action keeps when it was done on the phone, before it reached the server
    const offline = detail.events.filter((e: { action: string }) => ["check_in", "prechecks_done", "configured"].includes(e.action));
    for (const e of offline) expect(Date.parse(e.captured_at)).toBeLessThanOrEqual(Date.parse(e.at));
    expect(problems.filter((p) => !/Failed to fetch|ERR_INTERNET_DISCONNECTED|net::/.test(p))).toEqual([]);
    problems.length = 0;
  });
});
