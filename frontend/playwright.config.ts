import { defineConfig, devices } from "@playwright/test";

/**
 * Browser smoke tests against a running stack (docker compose up, then `cli demo-projects`).
 * BASE_URL defaults to the local `next dev` on 9594; set it to http://localhost:9595 to test
 * the built web container. Uses the installed Chrome, so no browser download is needed.
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "./e2e/.report", open: "never" }]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:9594",
    channel: "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 45_000,
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "phone", use: { ...devices["Pixel 7"], channel: "chrome" }, grep: /@phone/ },
  ],
});
