/* Service worker for the installed app.
 *
 * - Built assets (/_next/static, icons, logos) never change under the same URL: cache first.
 * - Pages: network first, keeping a copy of each page shell that loaded, so a task page that was
 *   open this morning still opens on a site with no signal. Pages carry no data: the data comes
 *   from /api, which is never cached here (prices and other roles' data never reach a cache).
 * - Versioned by the build: the page registers /sw.js?v=<build id>, so a new build installs a
 *   new worker. It waits until the person taps "Reload" (message p1-skip-waiting).
 * - Web Push: shows the message and opens its link when tapped.
 * - Background Sync (tag p1-outbox), where the browser has it: asks an open page to send the
 *   outbox, or sends it from here when no page is open. iPhones lack it; the page also sends on
 *   open, on reconnect and every 30 seconds, so nothing depends on it.
 */
const VERSION = `p1-${new URL(self.location.href).searchParams.get("v") || "dev"}`;
const STATIC = `${VERSION}-static`;
const PAGES = `${VERSION}-pages`;

self.addEventListener("install", () => {
  // wait for the person to choose the new version (see the message handler)
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "p1-skip-waiting") self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("p1-") && !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isStatic(url) {
  return url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/") || url.pathname.startsWith("/brand/");
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (isStatic(url)) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(STATIC).then((c) => c.put(req, copy));
            }
            return res;
          }),
      ),
    );
    return;
  }

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok && !url.pathname.startsWith("/upload/")) {
            const copy = res.clone();
            caches.open(PAGES).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(async () => (await caches.match(req)) || (await caches.match("/field")) || Response.error()),
    );
  }
});

// ------------------------------------------------------------------ Web Push

self.addEventListener("push", (event) => {
  let data = { title: "Project One", body: "", url: "/", tag: "p1" };
  try {
    data = { ...data, ...event.data.json() };
  } catch {
    /* not JSON: show the default */
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      tag: data.tag,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: data.url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url === target && "focus" in c) return c.focus();
      }
      return self.clients.openWindow(target);
    }),
  );
});

// ------------------------------------------------------------------ Background Sync

function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("p1-field", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("outbox", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function store(mode, fn) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const t = db.transaction("outbox", mode);
    const r = fn(t.objectStore("outbox"));
    t.oncomplete = () => resolve(r.result);
    t.onerror = () => reject(t.error);
  });
}

async function csrf() {
  try {
    const c = self.cookieStore ? await self.cookieStore.get("p1_csrf") : null;
    return c ? c.value : "";
  } catch {
    return "";
  }
}

async function call(method, path, init) {
  const headers = { ...(init.headers || {}), "X-CSRF-Token": await csrf() };
  return fetch(`/api/v1${path}`, { method, credentials: "same-origin", ...init, headers });
}

async function sendOutbox() {
  const me = await call("GET", "/auth/me", {});
  if (me.status === 401) {
    const r = await call("POST", "/auth/refresh", { headers: { "X-Auth-Mode": "cookie" } });
    if (!r.ok) throw new Error("signed out: the page sends the work after the next sign-in");
  } else if (!me.ok) {
    throw new Error(`server answered ${me.status}`);
  }
  const who = await (me.ok ? me : await call("GET", "/auth/me", {})).json();
  const items = (await store("readonly", (s) => s.getAll()))
    .filter((p) => !p.error && (!p.userId || p.userId === who.id))
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  for (const item of items) {
    let body;
    const headers = {};
    if (item.kind === "form") {
      body = new FormData();
      Object.entries(item.fields || {}).forEach(([k, v]) => body.append(k, v));
      if (item.file) body.append("file", item.file, item.fileName || "evidence");
      for (const x of item.extra || []) body.append(x.field, x.blob, x.name);
    } else {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(item.body || {});
    }
    const res = await call("POST", item.path, { headers, body });
    if (res.ok) {
      await store("readwrite", (s) => s.delete(item.id));
      continue;
    }
    if ([401, 408, 429, 502, 503, 504].includes(res.status)) throw new Error(`will retry (${res.status})`);
    let detail = `The server refused it (${res.status}).`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* not JSON */
    }
    await store("readwrite", (s) => s.put({ ...item, error: detail }));
  }
}

self.addEventListener("sync", (event) => {
  if (event.tag !== "p1-outbox") return;
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then(async (list) => {
      if (list.length) {
        list.forEach((c) => c.postMessage({ type: "p1-flush" }));
        return;
      }
      await sendOutbox();
      const after = await self.clients.matchAll({ type: "window" });
      after.forEach((c) => c.postMessage({ type: "p1-synced" }));
    }),
  );
});
