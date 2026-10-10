// Bundle size budget for the field engineer's pages, which load over mobile data.
// Run after `npm run build`: `npm run budget`. Counts every JavaScript file a first visit to the
// page downloads (framework, root and app layouts, the page), gzipped, as Next.js reports it.
// Fails when a page is over its budget, so a heavy import into the field app is caught early.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

// About 10 percent above the sizes on 8 Oct 2026 (146 and 151 kB). Next.js's own "First Load JS"
// figure is lower because it leaves out the shared app layout, which a phone does download.
const BUDGETS_KB = {
  "/(app)/field/page": 160,
  "/(app)/field/[id]/page": 165,
};

const next = join(import.meta.dirname, "..", ".next");
const app = JSON.parse(readFileSync(join(next, "app-build-manifest.json"), "utf8")).pages;
const root = JSON.parse(readFileSync(join(next, "build-manifest.json"), "utf8"));
const shared = [...(root.rootMainFiles ?? []), ...(root.polyfillFiles ?? [])];

const sizes = new Map();
const gz = (file) => {
  if (!sizes.has(file)) sizes.set(file, gzipSync(readFileSync(join(next, file))).length);
  return sizes.get(file);
};

let failed = false;
for (const [page, budget] of Object.entries(BUDGETS_KB)) {
  if (!app[page]) {
    console.error(`${page}: not in the build. Was it renamed? Update BUDGETS_KB.`);
    failed = true;
    continue;
  }
  const files = new Set(
    [...shared, ...(app["/layout"] ?? []), ...(app["/(app)/layout"] ?? []), ...app[page]].filter(
      (f) => f.endsWith(".js") && !f.includes("polyfills"),
    ),
  );
  const kb = [...files].reduce((sum, f) => sum + gz(f), 0) / 1024;
  const ok = kb <= budget;
  failed ||= !ok;
  console.log(`${ok ? "ok  " : "OVER"} ${page.padEnd(28)} ${kb.toFixed(1).padStart(6)} kB of ${budget} kB`);
}
process.exit(failed ? 1 : 0);
