# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: smoke.spec.ts >> Director >> dashboard, every page and the finished project
- Location: e2e\smoke.spec.ts:35:7

# Error details

```
Error: Problems on dashboard, every page and the finished project

expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 6

- Array []
+ Array [
+   "HTTP 404 GET /api/v1/projects/155501ca-0910-4dc6-8cf8-9f3edbea28ff/gaps",
+   "HTTP 404 GET /api/v1/projects/155501ca-0910-4dc6-8cf8-9f3edbea28ff/gaps",
+   "HTTP 404 GET /api/v1/projects/155501ca-0910-4dc6-8cf8-9f3edbea28ff/boq",
+   "HTTP 404 GET /api/v1/projects/155501ca-0910-4dc6-8cf8-9f3edbea28ff/boq",
+ ]
```

# Page snapshot

```yaml
- generic [ref=f12e1]:
  - button "Open Next.js Dev Tools" [ref=f12e7] [cursor=pointer]
  - alert [ref=f12e11]
  - generic [ref=f12e12]:
    - complementary [ref=f12e13]:
      - link "Project One ITCraft" [ref=f12e14] [cursor=pointer]:
        - /url: /projects
        - generic [ref=f12e15]:
          - text: Project One
          - generic "ITCraft" [ref=f12e17]: ITCRAFT
      - navigation "Main" [ref=f12e18]:
        - link "Review" [ref=f12e19] [cursor=pointer]:
          - /url: /review
        - link "Dashboard" [ref=f12e20] [cursor=pointer]:
          - /url: /dashboard
        - link "Projects" [ref=f12e21] [cursor=pointer]:
          - /url: /projects
        - link "Catalogue" [ref=f12e22] [cursor=pointer]:
          - /url: /catalogue
        - link "Library" [ref=f12e23] [cursor=pointer]:
          - /url: /library
        - link "Certificate" [ref=f12e24] [cursor=pointer]:
          - /url: /settings/certificate
      - generic [ref=f12e25]:
        - generic [ref=f12e26]:
          - generic [ref=f12e27]: Rajesh Iyer
          - generic [ref=f12e28]: director
        - button "Theme is system. Change theme" [ref=f12e29] [cursor=pointer]: "Theme: system"
        - button "Sign out" [ref=f12e30] [cursor=pointer]
    - generic [ref=f12e32]:
      - generic [ref=f12e33]:
        - generic [ref=f12e34]:
          - link "Projects" [ref=f12e36] [cursor=pointer]:
            - /url: /projects
          - heading "IT infrastructure hardening" [level=1] [ref=f12e37]
          - paragraph [ref=f12e38]: Shakti Equipments Pvt Ltd P1-2627-0001
        - generic [ref=f12e39]: active
      - list "Project stages" [ref=f12e40]:
        - listitem [ref=f12e41]:
          - generic [ref=f12e42]:
            - text: Audit intake
            - generic [ref=f12e43]: In progress
        - listitem [ref=f12e44]:
          - generic [ref=f12e45]:
            - text: Current IT
            - generic [ref=f12e46]: Locked
        - listitem [ref=f12e47]:
          - generic [ref=f12e48]:
            - text: Ideal IT
            - generic [ref=f12e49]: Locked
        - listitem [ref=f12e50]:
          - generic [ref=f12e51]:
            - text: Gap analysis
            - generic [ref=f12e52]: Locked
        - listitem [ref=f12e53]:
          - generic [ref=f12e54]:
            - text: BOQ
            - generic [ref=f12e55]: Locked
        - listitem [ref=f12e56]:
          - generic [ref=f12e57]:
            - text: Plan
            - generic [ref=f12e58]: Locked
        - listitem [ref=f12e59]:
          - generic [ref=f12e60]:
            - text: Field work
            - generic [ref=f12e61]: Locked
        - listitem [ref=f12e62]:
          - generic [ref=f12e63]:
            - text: Completion
            - generic [ref=f12e64]: Locked
      - tablist "Project sections" [ref=f12e65]:
        - tab "Overview" [ref=f12e66] [cursor=pointer]
        - tab "Audit intake" [ref=f12e67] [cursor=pointer]
        - tab "Questionnaire" [ref=f12e68] [cursor=pointer]
        - tab "Infrastructure" [ref=f12e69] [cursor=pointer]
        - tab "Gaps" [ref=f12e70] [cursor=pointer]
        - tab "BOQ" [ref=f12e71] [cursor=pointer]
        - tab "Plan" [ref=f12e72] [cursor=pointer]
        - tab "Field work" [ref=f12e73] [cursor=pointer]
        - tab "Completion" [active] [selected] [ref=f12e74] [cursor=pointer]
      - generic [ref=f12e75]:
        - generic [ref=f12e76]:
          - heading "Before the certificate" [level=2] [ref=f12e77]
          - generic [ref=f12e78]: 3 of 9 met
        - paragraph [ref=f12e79]: Every line must hold before a Director can sign. Nobody can override one; a task or deviation can only be excused by a waiver the customer accepts.
        - list [ref=f12e80]:
          - listitem [ref=f12e81]:
            - generic [ref=f12e83]:
              - generic [ref=f12e84]:
                - text: Every task is closed or excluded by an acknowledged waiver
                - generic [ref=f12e85]: ", not met"
              - generic [ref=f12e86]: No field work yet.
              - generic [ref=f12e87]:
                - text: Close the remaining tasks in
                - link "Field work" [ref=f12e88] [cursor=pointer]:
                  - /url: "#field"
                - text: ", or ask for a waiver below."
          - listitem [ref=f12e89]:
            - generic [ref=f12e91]:
              - generic [ref=f12e92]:
                - text: No open critical deviation
                - generic [ref=f12e93]: ", met"
              - generic [ref=f12e94]: None open
          - listitem [ref=f12e95]:
            - generic [ref=f12e97]:
              - generic [ref=f12e98]:
                - text: Every waiver is approved by the Director and acknowledged by the customer
                - generic [ref=f12e99]: ", met"
              - generic [ref=f12e100]: None waiting
          - listitem [ref=f12e101]:
            - generic [ref=f12e103]:
              - generic [ref=f12e104]:
                - text: The after-work PrismSuite rescan is approved
                - generic [ref=f12e105]: ", not met"
              - generic [ref=f12e106]: Upload the after-work PrismSuite report as a rescan and approve it.
          - listitem [ref=f12e107]:
            - generic [ref=f12e109]:
              - generic [ref=f12e110]:
                - text: The IITPL stamp is uploaded
                - generic [ref=f12e111]: ", met"
              - generic [ref=f12e112]: Uploaded
          - listitem [ref=f12e113]:
            - generic [ref=f12e115]:
              - generic [ref=f12e116]:
                - text: The completion report is locked
                - generic [ref=f12e117]: ", not met"
              - generic [ref=f12e118]: Not locked yet
          - listitem [ref=f12e119]:
            - generic [ref=f12e121]:
              - generic [ref=f12e122]:
                - text: The customer acknowledged the completion stage
                - generic [ref=f12e123]: ", not met"
              - generic [ref=f12e124]: Waiting for the customer's acknowledgement
          - listitem [ref=f12e125]:
            - generic [ref=f12e127]:
              - generic [ref=f12e128]:
                - text: A Director approved the completion stage (final check)
                - generic [ref=f12e129]: ", not met"
              - generic [ref=f12e130]: Waiting for the Director
          - listitem [ref=f12e131]:
            - generic [ref=f12e133]:
              - generic [ref=f12e134]:
                - text: The project is at the completion stage
                - generic [ref=f12e135]: ", not met"
              - generic [ref=f12e136]: audit intake
      - generic [ref=f12e137]:
        - heading "Open deviations" [level=2] [ref=f12e138]
        - paragraph [ref=f12e139]: Every setting matches its target, or was accepted or waived.
      - generic [ref=f12e140]:
        - heading "Waivers" [level=2] [ref=f12e142]
        - paragraph [ref=f12e143]: No waivers. Everything in the plan is expected to be done and verified.
      - generic [ref=f12e144]:
        - generic [ref=f12e145]:
          - heading "Completion report" [level=2] [ref=f12e146]
          - paragraph [ref=f12e147]: Work delivered, exclusions, before and after scores, configuration checks and deviations. No prices.
          - generic [ref=f12e148]:
            - link "Preview" [ref=f12e149] [cursor=pointer]:
              - /url: /api/v1/reporting/projects/155501ca-0910-4dc6-8cf8-9f3edbea28ff/report/preview?fmt=html
            - button "Lock the report" [disabled] [ref=f12e150]
        - generic [ref=f12e151]:
          - heading "Certificate" [level=2] [ref=f12e152]
          - generic [ref=f12e153]:
            - heading "Not ready to sign" [level=3] [ref=f12e154]
            - paragraph [ref=f12e155]: The certificate opens once every line of the list above holds.
          - button "Sign the certificate" [disabled] [ref=f12e157]
  - status
```

# Test source

```ts
  1   | import { createHmac } from "node:crypto";
  2   | import { existsSync, mkdirSync, readFileSync } from "node:fs";
  3   | import path from "node:path";
  4   | import { expect, test as base, type Page } from "@playwright/test";
  5   | 
  6   | /** Written by `python -m app.cli demo-projects --out .demo/demo-accounts.json`. */
  7   | type Account = { email: string; name: string; roles: string[]; totp_secret: string | null };
  8   | type Accounts = { password: string; certificate: string | null; users: Account[] };
  9   | 
  10  | const FILE = path.resolve(__dirname, "../../.demo/demo-accounts.json");
  11  | export const accounts: Accounts = JSON.parse(readFileSync(FILE, "utf-8"));
  12  | export const SHOTS = path.resolve(__dirname, "screens");
  13  | if (!existsSync(SHOTS)) mkdirSync(SHOTS, { recursive: true });
  14  | 
  15  | export function who(role: string): Account {
  16  |   const a = accounts.users.find((u) => u.roles.includes(role));
  17  |   if (!a) throw new Error(`No demo account with role ${role}`);
  18  |   return a;
  19  | }
  20  | 
  21  | /** RFC 6238 time-based code, the same an authenticator app shows. */
  22  | export function totp(secret: string, at = Date.now()): string {
  23  |   const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  24  |   let bits = "";
  25  |   for (const ch of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  26  |   const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  27  |   const counter = Buffer.alloc(8);
  28  |   counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  29  |   const h = createHmac("sha1", key).update(counter).digest();
  30  |   const o = h[h.length - 1] & 0xf;
  31  |   const n = ((h[o] & 0x7f) << 24) | (h[o + 1] << 16) | (h[o + 2] << 8) | h[o + 3];
  32  |   return String(n % 1_000_000).padStart(6, "0");
  33  | }
  34  | 
  35  | const usedStep = new Map<string, number>();
  36  | 
  37  | export async function signIn(page: Page, role: string): Promise<Account> {
  38  |   const a = who(role);
  39  |   await page.goto("/login");
  40  |   await page.locator("#email").fill(a.email);
  41  |   await page.locator("#password").fill(accounts.password);
  42  |   await page.getByRole("button", { name: "Sign in", exact: true }).click();
  43  |   if (a.totp_secret) {
  44  |     await page.locator("#code").waitFor();
  45  |     // A code is accepted once; a second sign-in in the same 30 seconds waits for the next one.
  46  |     const step = Math.floor(Date.now() / 30_000);
  47  |     if (usedStep.get(a.email) === step) await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 500);
  48  |     usedStep.set(a.email, Math.floor(Date.now() / 30_000));
  49  |     await page.locator("#code").fill(totp(a.totp_secret));
  50  |     await page.getByRole("button", { name: "Verify", exact: true }).click();
  51  |   }
  52  |   await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  53  |   await page.locator("nav.nav a").first().waitFor();
  54  |   return a;
  55  | }
  56  | 
  57  | /**
  58  |  * Every page visit records what went wrong: console errors, server errors (5xx) and
  59  |  * error notices on the page. A test fails if any of them happened.
  60  |  */
  61  | const expected = new WeakMap<Page, RegExp[]>();
  62  | /** Declare responses a test causes on purpose (a bad link answering 404, say). */
  63  | export function expectFailure(page: Page, url: RegExp) {
  64  |   expected.set(page, [...(expected.get(page) ?? []), url]);
  65  | }
  66  | 
  67  | export const test = base.extend<{ problems: string[] }>({
  68  |   problems: async ({ page }, use, info) => {
  69  |     const problems: string[] = [];
  70  |     page.on("console", (m) => {
  71  |       if (m.type() === "error" && !/favicon|Download the React DevTools|Failed to load resource/.test(m.text()))
  72  |         problems.push(`console: ${m.text().slice(0, 300)}`);
  73  |     });
  74  |     page.on("pageerror", (e) => problems.push(`page error: ${e.message.slice(0, 300)}`));
  75  |     page.on("response", (r) => {
  76  |       const url = new URL(r.url());
  77  |       const s = r.status();
  78  |       const api = url.pathname.startsWith("/api/");
  79  |       if (s >= 500 || (api && s >= 400 && s !== 401 && !(expected.get(page) ?? []).some((x) => x.test(url.pathname))))
  80  |         problems.push(`HTTP ${s} ${r.request().method()} ${url.pathname}${url.search}`);
  81  |     });
  82  |     await use(problems);
  83  |     if (problems.length) info.annotations.push({ type: "problems", description: problems.join("\n") });
> 84  |     expect(problems, `Problems on ${info.title}`).toEqual([]);
      |                                                   ^ Error: Problems on dashboard, every page and the finished project
  85  |   },
  86  | });
  87  | 
  88  | /** Open a page, wait for its data, check for error notices, save a screenshot. */
  89  | export async function visit(page: Page, url: string, shot: string, opts: { allowNotice?: RegExp } = {}) {
  90  |   await page.goto(url);
  91  |   await settle(page);
  92  |   const notices = await page.locator(".notice.bad").allInnerTexts();
  93  |   const real = notices.filter((t) => !(opts.allowNotice && opts.allowNotice.test(t)));
  94  |   expect(real, `error notices on ${url}`).toEqual([]);
  95  |   await page.screenshot({ path: path.join(SHOTS, `${shot}.png`), fullPage: true });
  96  | }
  97  | 
  98  | export async function settle(page: Page) {
  99  |   await page.waitForLoadState("networkidle").catch(() => undefined);
  100 |   await page.locator('[aria-busy="true"]').first().waitFor({ state: "detached", timeout: 15_000 }).catch(() => undefined);
  101 | }
  102 | 
  103 | export { expect };
  104 | 
```