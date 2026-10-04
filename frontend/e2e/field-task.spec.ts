import type { Page } from "@playwright/test";
import { everyone, expect, settle, signIn, signInAs, test } from "./support";

/**
 * One field task from start to finish on a phone: accept, check in with the customer's code,
 * prechecks, steps, evidence, the check, hand over with the customer's code, then the technical
 * lead approves it. Each run uses up one task that is still "assigned" in the demo data (the demo
 * has dozens); rebuild the demo when they run out. Codes are read from Mailpit, as a customer
 * would read them from their email.
 */
const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:9605";
// A 2x2 PNG: enough for the photo evidence pipeline (type sniffing, virus scan, storage).
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP4z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==",
  "base64",
);

type Run = { id: string; state: string; task_ref: string };

/** The newest code email with this subject that arrived after `since`. */
async function codeFromEmail(page: Page, subject: string, since: number): Promise<string> {
  for (let i = 0; i < 60; i++) {
    const list = await (await page.request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`subject:"${subject}"`)}`)).json();
    const fresh = (list.messages ?? []).find((m: { Created: string }) => Date.parse(m.Created) >= since);
    if (fresh) {
      const msg = await (await page.request.get(`${MAILPIT}/api/v1/message/${fresh.ID}`)).json();
      const code = /\b(\d{6})\b/.exec(msg.Text ?? "")?.[1];
      if (code) return code;
    }
    await page.waitForTimeout(1000);
  }
  throw new Error(`No "${subject}" email arrived in Mailpit`);
}

async function enterCustomerCode(page: Page, purpose: "check_in" | "handover", subject: string, label: string) {
  const since = Date.now() - 2000;
  await page.getByRole("button", { name: "Send code to the customer" }).click();
  await page.locator(`#otp-${purpose}`).fill(await codeFromEmail(page, subject, since));
  await page.getByRole("button", { name: label, exact: true }).click();
  await settle(page);
}

/** Satisfy every evidence request on screen: a photo for file inputs, text for the rest. */
async function addEvidence(page: Page) {
  // An uploaded photo's input goes away, so look again after each one.
  for (let n = 0; n < 20; n++) {
    const files = page.locator('input[type="file"]');
    const before = await files.count();
    if (!before) break;
    await files.first().setInputFiles({ name: "evidence.png", mimeType: "image/png", buffer: PNG });
    await expect(files).toHaveCount(before - 1);
    await settle(page);
    await expect(page.getByText(/saved on this phone, waiting for signal/)).toHaveCount(0);
  }
  // A saved item loses its field, so look again after each save.
  for (let n = 0; n < 20; n++) {
    const next = page.locator('input[id^="ev-"]:visible, textarea[id^="ev-"]:visible').first();
    if (!(await next.count())) break;
    // pin this one field by its id: "the first visible field" changes as items are saved
    const field = page.locator(`[id="${await next.getAttribute("id")}"]`);
    await field.fill("Checked with the customer's IT contact present");
    await field.locator("xpath=ancestor::form[1]").getByRole("button", { name: "Save" }).click();
    await expect(field).toBeHidden(); // saved: the item shows as added
    await settle(page);
  }
}

/**
 * Press a button that moves the task to its next state, and wait until the server says it moved.
 * A click that lands in the instant the page redraws is lost before it reaches the app (nothing
 * is sent), so if the state has not moved, press again. A refused action still fails the test.
 */
async function advance(page: Page, runId: string, button: string) {
  const state = async () => (await (await page.request.get(`/api/v1/field/runs/${runId}`)).json()).run.state;
  const before = await state();
  for (let attempt = 0; attempt < 3; attempt++) {
    await settle(page);
    await page.getByRole("button", { name: button, exact: true }).click();
    try {
      await expect.poll(state, { timeout: 6_000 }).not.toBe(before);
      await settle(page);
      return;
    } catch {
      /* the click did not reach the app: press again */
    }
  }
  throw new Error(`"${button}" did not move the task on from ${before}`);
}

test.describe("Field engineer @phone", () => {
  test("one task from accept to verified @phone", async ({ page, problems }, info) => {
    test.skip(info.project.name !== "phone", "walks a real task; runs once, on the phone");
    test.setTimeout(240_000);
    await page.context().grantPermissions(["geolocation"]);
    await page.context().setGeolocation({ latitude: 19.1972, longitude: 72.9722 });
    // the first field engineer with an assigned task that needs photos and notes only, and is not
    // waiting for another task (device values and configuration files go through the
    // configuration check, which the backend tests cover value by value)
    let run: Run | undefined;
    for (const engineer of everyone("field_engineer")) {
      await page.context().clearCookies();
      await signInAs(page, engineer);
      const mine: Run[] = await (await page.request.get("/api/v1/field/my")).json();
      for (const r of mine.filter((x) => x.state === "assigned")) {
        const d = await (await page.request.get(`/api/v1/field/runs/${r.id}`)).json();
        const simple =
          !d.run.baseline?.length &&
          !(d.run.evidence_reqs ?? []).some((e: { type: string }) => e.type === "config_export");
        if (!d.waiting_on?.length && simple) {
          run = r;
          break;
        }
      }
      if (run) break;
    }
    test.skip(!run, "no assigned task left in the demo data: rebuild the demo");

    await page.goto(`/field/${run!.id}`);
    await advance(page, run!.id, "Accept task");

    await expect(page.getByRole("heading", { name: "Arrive on site" })).toBeVisible();
    // the code cannot be asked for until the arrival evidence is in
    if (await page.locator('input[type="file"], input[id^="ev-"]').count()) {
      await expect(page.getByRole("button", { name: "Send code to the customer" })).toBeDisabled();
      await addEvidence(page);
    }
    await enterCustomerCode(page, "check_in", "visit code", "Check in");

    await expect(page.getByRole("heading", { name: "Before you change anything" })).toBeVisible();
    await addEvidence(page);
    await advance(page, run!.id, "Mark prechecks done");

    await expect(page.getByRole("heading", { name: "Steps" })).toBeVisible();
    const steps = page.locator(".steps li");
    const total = await steps.count();
    for (let i = 0; i < total; i++) {
      await steps.nth(i).getByRole("button", { name: "Done" }).click();
      await expect(steps.nth(i)).toHaveAttribute("data-done", "true");
    }
    await advance(page, run!.id, "Mark configured");

    await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
    await addEvidence(page);
    await advance(page, run!.id, "Send for the check");

    await expect(page.getByRole("heading", { name: "Hand over to the customer" })).toBeVisible();
    await enterCustomerCode(page, "handover", "hand over code", "Confirm hand over");
    const state = async () => (await (await page.request.get(`/api/v1/field/runs/${run!.id}`)).json()).run.state;
    await expect.poll(state, { timeout: 20_000 }).toBe("verifier_review");

    // the technical lead checks the work and closes it
    await page.context().clearCookies();
    await signIn(page, "technical_lead");
    await page.goto(`/field/${run!.id}`);
    await page.getByRole("button", { name: "Approve and close" }).click();
    await settle(page);
    await expect.poll(state, { timeout: 20_000 }).toBe("closed");
    expect(problems).toEqual([]);
  });
});
