import type { Page } from "@playwright/test";
import { expect, expectFailure, settle, signIn, test } from "./support";

/**
 * Work left on the phone for more than 24 hours is called out before the server's 72 hour limit
 * refuses it (ADR 0027). The test puts one old item straight into the outbox; it points at a task
 * that does not exist, so the server refuses it and it stays on the phone until removed.
 */
const ID = "e2e-late-item";
const PATH = "/field/runs/00000000-0000-0000-0000-000000000000/accept";

function outbox(page: Page, put: boolean) {
  return page.evaluate(
    ([id, path, put]) =>
      new Promise<void>((resolve, reject) => {
        const req = indexedDB.open("p1-field", 1);
        req.onupgradeneeded = () => req.result.createObjectStore("outbox", { keyPath: "id" });
        req.onerror = () => reject(req.error);
        req.onsuccess = () => {
          const t = req.result.transaction("outbox", "readwrite");
          const s = t.objectStore("outbox");
          if (put) {
            const createdAt = new Date(Date.now() - 25 * 3_600_000).toISOString();
            s.put({ id, runId: "e2e", label: "Accept (test)", createdAt, kind: "json", path, body: {} });
          } else s.delete(id);
          t.oncomplete = () => resolve();
          t.onerror = () => reject(t.error);
        };
      }),
    [ID, PATH, put] as const,
  );
}

test.describe("Field engineer @phone", () => {
  test("warns when work has waited on the phone for more than 24 hours @phone", async ({ page, problems }) => {
    expectFailure(page, /\/field\/runs\/0{8}-0{4}-0{4}-0{4}-0{12}\/accept$/);
    await signIn(page, "field_engineer");
    await page.goto("/field");
    await settle(page);
    await expect(page.getByText("more than 24 hours")).toHaveCount(0);

    await outbox(page, true);
    try {
      await page.reload();
      await settle(page);
      await expect(page.getByText("waited on the phone for more than 24 hours")).toBeVisible();
      await expect(page.locator(".sync-badge")).toHaveClass(/\bbad\b/);
    } finally {
      await outbox(page, false);
    }
    await page.reload();
    await settle(page);
    await expect(page.getByText("more than 24 hours")).toHaveCount(0);
    expect(problems).toEqual([]);
  });
});
