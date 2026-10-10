"use client";
/**
 * The field outbox. Every engineer action is saved on the phone first, then sent. With no signal
 * it waits and is sent when the phone is back online. Each action carries `client_event_id`
 * (or `client_id` for evidence) and `captured_at`, so the server ignores a resend and records
 * when the work really happened (up to 72 hours earlier).
 *
 * Stored in IndexedDB so photos survive a closed browser. Sent in order: on every save, when the
 * app opens or comes back to the front, when the phone reconnects, every 30 seconds, and through
 * Background Sync where the browser has it (public/sw.js; never relied on, iPhones lack it).
 * Each item belongs to the person who saved it; only that person's sign-in sends it.
 */
import { api, message, passing } from "./api";

export type ExtraFile = { field: string; blob: Blob; name: string };

export type Pending = {
  id: string;
  runId: string;
  label: string;
  createdAt: string;
  kind: "json" | "form";
  path: string;
  body?: Record<string, unknown>;
  fields?: Record<string, string>;
  file?: Blob;
  fileName?: string;
  extra?: ExtraFile[];
  error?: string;
  userId?: string;
};

export type OutboxState = {
  waiting: number;
  uploading: string | null; // label of the item being sent
  failed: number;
  others: number; // saved by someone else who used this phone
  lastSyncAt: string | null;
  online: boolean;
};

const DB = "p1-field";
const STORE = "outbox";
const LAST_SYNC = "p1-last-sync";
const listeners = new Set<() => void>();
let currentUser: string | null = null;
let reportsStatus = false;
let uploading: string | null = null;

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const r = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(r.result);
    t.onerror = () => reject(t.error);
  });
}

const notify = () => listeners.forEach((l) => l());

// What the server accepted, kept for a while: when the signal drops right after a send, the page
// cannot reload the task and would show it as it was before (offering Accept again, a photo as
// still needed). The page lays these over its older copy, like the work still waiting. Kept under
// the offline-data prefix, so signing out clears it (forgetKept).
const SENT = "p1-kept:sent";
const SENT_FOR_MS = 72 * 3_600_000;
export type Sent = { runId: string; path: string; body?: Record<string, unknown>; fields?: Record<string, string>; at: number };

function readSent(): Sent[] {
  try {
    return JSON.parse(localStorage.getItem(SENT) ?? "[]") as Sent[];
  } catch {
    return [];
  }
}

function rememberSent(item: Pending) {
  const now = Date.now();
  const kept = readSent().filter((x) => now - x.at < SENT_FOR_MS).slice(-99);
  kept.push({ runId: item.runId, path: item.path, body: item.body, fields: item.fields, at: now });
  try {
    localStorage.setItem(SENT, JSON.stringify(kept));
  } catch {
    /* storage full or blocked: the page reloads from the server instead */
  }
}

/** This task's actions and evidence the server accepted after `since` (ms since 1970). */
export function sentAfter(runId: string, since: number): Sent[] {
  return readSent().filter((x) => x.runId === runId && x.at > since);
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Who is signed in on this phone. Only their saved work is sent; `field` says whether to report
 * the outbox to the server for the Director's view. */
export function setOutboxUser(id: string | null, field = false) {
  const changed = id !== currentUser;
  currentUser = id;
  reportsStatus = field && !!id;
  notify();
  // Sync on app open: the first thing once we know who is signed in.
  if (id && changed) void flush().catch(() => undefined);
}

const mine = (p: Pending) => !p.userId || p.userId === currentUser;

async function all(): Promise<Pending[]> {
  const items = await tx<Pending[]>("readonly", (s) => s.getAll() as IDBRequest<Pending[]>);
  return items.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/** The signed-in person's saved work, oldest first. */
export async function pending(runId?: string): Promise<Pending[]> {
  return (await all()).filter((p) => mine(p) && (!runId || p.runId === runId));
}

function lastSync(): string | null {
  try {
    return localStorage.getItem(LAST_SYNC);
  } catch {
    return null;
  }
}

export async function outboxState(): Promise<OutboxState> {
  const items = await all().catch(() => [] as Pending[]);
  const own = items.filter(mine);
  return {
    waiting: own.filter((p) => !p.error).length,
    uploading,
    failed: own.filter((p) => p.error).length,
    others: items.length - own.length,
    lastSyncAt: lastSync(),
    online: typeof navigator === "undefined" ? true : navigator.onLine,
  };
}

function askBackgroundSync() {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  navigator.serviceWorker.ready
    .then((reg) => (reg as ServiceWorkerRegistration & { sync?: { register(tag: string): Promise<void> } }).sync?.register("p1-outbox"))
    .catch(() => undefined);
}

async function save(item: Pending): Promise<FlushResult> {
  await tx("readwrite", (s) => s.put({ ...item, userId: currentUser ?? undefined }));
  notify();
  askBackgroundSync();
  return flush();
}

/** Save a JSON action (accept, check in, step done...) and try to send it at once. */
export async function queueAction(runId: string, path: string, label: string, body: Record<string, unknown> = {}) {
  const id = crypto.randomUUID();
  return save({
    id,
    runId,
    label,
    createdAt: new Date().toISOString(),
    kind: "json",
    path,
    body: { ...body, client_event_id: id, captured_at: new Date().toISOString() },
  });
}

/** Save one piece of evidence (photo, file or text) and try to send it at once. */
export async function queueEvidence(
  runId: string,
  index: number,
  label: string,
  input: {
    file?: File | Blob | null;
    fileName?: string;
    text?: string;
    note?: string;
    extra?: ExtraFile[];
    location?: { lat: number; lng: number; accuracy_m?: number } | null;
    locationNote?: string;
  },
) {
  const id = crypto.randomUUID();
  const fields: Record<string, string> = {
    requirement_index: String(index),
    client_id: id,
    captured_at: new Date().toISOString(),
  };
  if (input.text) fields.text_value = input.text;
  if (input.note) fields.note = input.note;
  if (input.location) {
    fields.lat = String(input.location.lat);
    fields.lng = String(input.location.lng);
    if (input.location.accuracy_m !== undefined) fields.accuracy_m = String(input.location.accuracy_m);
  } else if (input.locationNote) {
    fields.location_note = input.locationNote.slice(0, 200);
  }
  return save({
    id,
    runId,
    label,
    createdAt: fields.captured_at,
    kind: "form",
    path: `/field/runs/${runId}/evidence`,
    fields,
    file: input.file ?? undefined,
    fileName: input.fileName ?? (input.file instanceof File ? input.file.name : undefined),
    extra: input.extra,
  });
}

export async function discard(id: string) {
  await tx("readwrite", (s) => s.delete(id));
  notify();
  void report(true);
}

/** Send a refused item again, for when the reason has been dealt with. */
export async function retry(id: string) {
  const item = await tx<Pending | undefined>("readonly", (s) => s.get(id) as IDBRequest<Pending | undefined>);
  if (!item) return flush();
  await tx("readwrite", (s) => s.put({ ...item, error: undefined }));
  notify();
  return flush();
}

let running: Promise<FlushResult> | null = null;
export type FlushResult = { sent: number; waiting: number; failed: string[] };

/** Send everything in order. Stops at the first failure that may pass (no signal, the server
 * restarting or busy, the sign-in to renew); an action the server refuses is kept with its
 * reason so the engineer can see it, then send it again or remove it. Server state wins. */
export function flush(): Promise<FlushResult> {
  // A send is already going: it only covers what was waiting when it started, so anything
  // saved since then goes in a second send right after it (otherwise it would sit on the
  // phone as "waiting for signal" with the signal fine).
  if (running) return running.then(() => flush());
  running = (async () => {
    const out: FlushResult = { sent: 0, waiting: 0, failed: [] };
    if (!currentUser) return out; // nobody signed in: keep everything for its owner
    for (const item of await pending()) {
      if (item.error) {
        out.failed.push(`${item.label}: ${item.error}`);
        continue;
      }
      uploading = item.label;
      notify();
      try {
        if (item.kind === "form") {
          const form = new FormData();
          Object.entries(item.fields ?? {}).forEach(([k, v]) => form.append(k, v));
          if (item.file) form.append("file", item.file, item.fileName ?? "evidence");
          for (const x of item.extra ?? []) form.append(x.field, x.blob, x.name);
          await api("POST", item.path, undefined, { form });
        } else {
          await api("POST", item.path, item.body);
        }
        rememberSent(item);
        await tx("readwrite", (s) => s.delete(item.id));
        out.sent += 1;
      } catch (e) {
        if (passing(e)) {
          out.waiting = (await pending()).filter((p) => !p.error).length;
          break; // try again later
        }
        await tx("readwrite", (s) => s.put({ ...item, error: message(e) }));
        out.failed.push(`${item.label}: ${message(e)}`);
      }
    }
    uploading = null;
    if (out.sent && !out.waiting) {
      try {
        localStorage.setItem(LAST_SYNC, new Date().toISOString());
      } catch {
        /* storage blocked */
      }
    }
    notify();
    void report(out.sent > 0 || out.failed.length > 0);
    return out;
  })().finally(() => {
    running = null;
    uploading = null;
  });
  return running;
}

let lastReport = 0;
let lastReported = "";
/** Tell the server what is waiting on this phone, so the Director sees "offline, 3 waiting,
 * last sync 14:02" instead of a task that looks stuck. At most once a minute unless it changed. */
async function report(force = false) {
  if (!reportsStatus || typeof navigator === "undefined" || !navigator.onLine) return;
  const st = await outboxState();
  const own = await pending().catch(() => [] as Pending[]);
  const key = `${st.waiting}:${st.failed}`;
  if (!force && key === lastReported && Date.now() - lastReport < 60_000) return;
  lastReport = Date.now();
  lastReported = key;
  try {
    await api("POST", "/field/device-status", {
      pending: st.waiting,
      failed: st.failed,
      oldest_pending_at: own.find((p) => !p.error)?.createdAt ?? null,
      last_sync_at: st.lastSyncAt,
      app_version: process.env.NEXT_PUBLIC_BUILD_ID ?? null,
      platform: /iPhone|iPad/.test(navigator.userAgent) ? "iPhone" : /Android/.test(navigator.userAgent) ? "Android" : "Desktop",
    });
  } catch {
    /* the next sync reports again */
  }
}

// Signal can come back without an "online" event (the server was down, or the phone had a
// weak connection), so also try when the app comes to the front and every 30 seconds.
if (typeof window !== "undefined") {
  // Storage can be blocked (a private window); then there is nothing saved to send.
  const quietly = () => void flush().catch(() => undefined);
  window.addEventListener("online", quietly);
  window.addEventListener("offline", notify);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") quietly();
  });
  setInterval(() => {
    if (navigator.onLine && document.visibilityState === "visible") quietly();
  }, 30_000);
  // The service worker asks the open page to send when Background Sync fires.
  navigator.serviceWorker?.addEventListener("message", (e: MessageEvent) => {
    if (e.data?.type === "p1-flush") quietly();
    if (e.data?.type === "p1-synced") notify();
  });
}
