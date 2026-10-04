import { createHmac } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { expect, test as base, type Page } from "@playwright/test";

/** Written by `python -m app.cli demo-projects --out .demo/demo-accounts.json`. */
type Account = { email: string; name: string; roles: string[]; totp_secret: string | null };
type Accounts = { password: string; certificate: string | null; users: Account[] };

const FILE = path.resolve(__dirname, "../../.demo/demo-accounts.json");
export const accounts: Accounts = JSON.parse(readFileSync(FILE, "utf-8"));
export const SHOTS = path.resolve(__dirname, "screens");
if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });

export function who(role: string): Account {
  const a = accounts.users.find((u) => u.roles.includes(role));
  if (!a) throw new Error(`No demo account with role ${role}`);
  return a;
}

/** RFC 6238 time-based code, the same an authenticator app shows. */
export function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  return String(n % 1_000_000).padStart(6, "0");
}

const usedStep = new Map<string, number>();

export async function signIn(page: Page, role: string): Promise<Account> {
  return signInAs(page, who(role));
}

/** Every demo account with this role, for tests that need a particular person. */
export const everyone = (role: string): Account[] => accounts.users.filter((u) => u.roles.includes(role));

export async function signInAs(page: Page, a: Account): Promise<Account> {
  await page.goto("/login");
  await page.locator("#email").fill(a.email);
  await page.locator("#password").fill(accounts.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  if (a.totp_secret) {
    await page.locator("#code").waitFor();
    // A code is accepted once; a second sign-in in the same 30 seconds waits for the next one.
    const step = Math.floor(Date.now() / 30_000);
    if (usedStep.get(a.email) === step) await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 500);
    usedStep.set(a.email, Math.floor(Date.now() / 30_000));
    await page.locator("#code").fill(totp(a.totp_secret));
    await page.getByRole("button", { name: "Verify", exact: true }).click();
  }
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  await page.locator("nav.nav a").first().waitFor();
  return a;
}

/**
 * Every page visit records what went wrong: console errors, server errors (5xx) and
 * error notices on the page. A test fails if any of them happened.
 */
const expected = new WeakMap<Page, RegExp[]>();
/** Declare responses a test causes on purpose (a bad link answering 404, say). */
export function expectFailure(page: Page, url: RegExp) {
  expected.set(page, [...(expected.get(page) ?? []), url]);
}

export const test = base.extend<{ problems: string[] }>({
  problems: async ({ page }, use, info) => {
    const problems: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error" && !/favicon|Download the React DevTools|Failed to load resource/.test(m.text()))
        problems.push(`console: ${m.text().slice(0, 300)}`);
    });
    page.on("pageerror", (e) => problems.push(`page error: ${e.message.slice(0, 300)}`));
    page.on("response", (r) => {
      const url = new URL(r.url());
      const s = r.status();
      const api = url.pathname.startsWith("/api/");
      if (s >= 500 || (api && s >= 400 && s !== 401 && !(expected.get(page) ?? []).some((x) => x.test(url.pathname))))
        problems.push(`HTTP ${s} ${r.request().method()} ${url.pathname}${url.search}`);
    });
    await use(problems);
    if (problems.length) info.annotations.push({ type: "problems", description: problems.join("\n") });
    expect(problems, `Problems on ${info.title}`).toEqual([]);
  },
});

/** Open a page, wait for its data, check for error notices, save a screenshot. */
export async function visit(page: Page, url: string, shot: string, opts: { allowNotice?: RegExp } = {}) {
  await page.goto(url);
  await settle(page);
  const notices = await page.locator(".notice.bad").allInnerTexts();
  const real = notices.filter((t) => !(opts.allowNotice && opts.allowNotice.test(t)));
  expect(real, `error notices on ${url}`).toEqual([]);
  await page.screenshot({ path: path.join(SHOTS, `${shot}.png`), fullPage: true });
}

export async function settle(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.locator('[aria-busy="true"]').first().waitFor({ state: "detached", timeout: 15_000 }).catch(() => undefined);
}

export { expect };
