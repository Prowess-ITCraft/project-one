// Lighthouse on the field engineer's pages, as a mid-range phone on slow 4G sees them (Lighthouse's
// mobile defaults: simulated slow 4G and a 4x slower processor). Run against the built web app:
//
//   BASE_URL=http://localhost:9595 npm run lighthouse
//
// Signs in as a demo field engineer in a Chrome that Lighthouse then attaches to, so the signed-in
// pages are measured, not the sign-in redirect. Fails when a page is under a threshold. Lighthouse
// 12 has no PWA category any more; installability is checked by e2e/pwa.spec.ts.
import { createHmac } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "@playwright/test";
import lighthouse from "lighthouse";

const THRESHOLDS = { performance: 0.8, accessibility: 0.95, "best-practices": 0.9 };
const BASE = process.env.BASE_URL ?? "http://localhost:9595";
const PORT = 9333;

const accounts = JSON.parse(readFileSync(join(import.meta.dirname, "../../.demo/demo-accounts.json"), "utf8"));
const engineer = accounts.users.find((u) => u.roles.includes("field_engineer"));

function totp(secret) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(n % 1_000_000).padStart(6, "0");
}

const profile = mkdtempSync(join(tmpdir(), "p1-lighthouse-"));
const browser = await chromium.launchPersistentContext(profile, {
  channel: "chrome",
  headless: true,
  args: [`--remote-debugging-port=${PORT}`],
});
let failed = false;

async function measure(name, path) {
  const config = { extends: "lighthouse:default", settings: { onlyCategories: Object.keys(THRESHOLDS) } };
  // Keep the sign-in cookie between pages; the sign-in page is measured before signing in.
  const flags = { port: PORT, output: "json", logLevel: "error", disableStorageReset: true };
  const { lhr } = await lighthouse(`${BASE}${path}`, flags, config);
  const scores = Object.entries(THRESHOLDS).map(([id, min]) => {
    const score = lhr.categories[id]?.score ?? 0;
    if (score < min) failed = true;
    return `${id} ${Math.round(score * 100)}${score < min ? ` (under ${min * 100})` : ""}`;
  });
  const lcp = lhr.audits["largest-contentful-paint"]?.displayValue ?? "?";
  const tbt = lhr.audits["total-blocking-time"]?.displayValue ?? "?";
  console.log(`${name.padEnd(10)} ${scores.join(", ")}; largest paint ${lcp}, blocking ${tbt}`);
}

try {
  await measure("sign-in", "/login");

  const page = await browser.newPage();
  await page.goto(`${BASE}/login`);
  await page.locator("#email").fill(engineer.email);
  await page.locator("#password").fill(accounts.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  if (engineer.totp_secret) {
    await page.locator("#code").fill(totp(engineer.totp_secret));
    await page.getByRole("button", { name: "Verify", exact: true }).click();
  }
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  await page.goto(`${BASE}/field`);
  const task = page.locator('a[href^="/field/"]').first();
  await task.waitFor({ timeout: 20_000 }).catch(() => undefined);
  const taskHref = (await task.count()) ? await task.getAttribute("href") : null;

  await measure("my tasks", "/field");
  if (taskHref) await measure("one task", taskHref);
  else console.log("No task assigned to the demo engineer; the task page is not measured.");
} finally {
  await browser.close();
  rmSync(profile, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
