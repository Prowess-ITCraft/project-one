"use client";
/**
 * The field outbox. Every engineer action is saved on the phone first, then sent. With no signal
 * it waits and is sent when the phone is back online. Each action carries `client_event_id`
 * (or `client_id` for evidence) and `captured_at`, so the server ignores a resend and records
 * when the work really happened (up to 72 hours earlier).
 *
 * Stored in IndexedDB so photos survive a closed browser. No library: about 100 lines.
 */
import { api, ApiError, message } from "./api";

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
  error?: string;
};

const DB = "p1-field";
const STORE = "outbox";
const listeners = new Set<() => void>();

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

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export async function pending(runId?: string): Promise<Pending[]> {
  const all = await tx<Pending[]>("readonly", (s) => s.getAll() as IDBRequest<Pending[]>);
  return all
    .filter((p) => !runId || p.runId === runId)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/** Save a JSON action (accept, check in, step done...) and try to send it at once. */
export async function queueAction(runId: string, path: string, label: string, body: Record<string, unknown> = {}) {
  const id = crypto.randomUUID();
  const item: Pending = {
    id,
    runId,
    label,
    createdAt: new Date().toISOString(),
    kind: "json",
    path,
    body: { ...body, client_event_id: id, captured_at: new Date().toISOString() },
  };
  await tx("readwrite", (s) => s.put(item));
  notify();
  return flush();
}

/** Save one piece of evidence (photo, file or text) and try to send it at once. */
export async function queueEvidence(
  runId: string,
  index: number,
  label: string,
  input: { file?: File | null; text?: string; note?: string },
) {
  const id = crypto.randomUUID();
  const fields: Record<string, string> = {
    requirement_index: String(index),
    client_id: id,
    captured_at: new Date().toISOString(),
  };
  if (input.text) fields.text_value = input.text;
  if (input.note) fields.note = input.note;
  const item: Pending = {
    id,
    runId,
    label,
    createdAt: fields.captured_at,
    kind: "form",
    path: `/field/runs/${runId}/evidence`,
    fields,
    file: input.file ?? undefined,
    fileName: input.file?.name,
  };
  await tx("readwrite", (s) => s.put(item));
  notify();
  return flush();
}

export async function discard(id: string) {
  await tx("readwrite", (s) => s.delete(id));
  notify();
}

let running: Promise<FlushResult> | null = null;
export type FlushResult = { sent: number; waiting: number; failed: string[] };

/** Send everything in order. Stops at the first network failure (still offline); an action the
 * server refuses is kept with its reason so the engineer can see it and discard it. */
export function flush(): Promise<FlushResult> {
  running ??= (async () => {
    const out: FlushResult = { sent: 0, waiting: 0, failed: [] };
    for (const item of await pending()) {
      if (item.error) {
        out.failed.push(`${item.label}: ${item.error}`);
        continue;
      }
      try {
        if (item.kind === "form") {
          const form = new FormData();
          Object.entries(item.fields ?? {}).forEach(([k, v]) => form.append(k, v));
          if (item.file) form.append("file", item.file, item.fileName ?? "evidence");
          await api("POST", item.path, undefined, { form });
        } else {
          await api("POST", item.path, item.body);
        }
        await tx("readwrite", (s) => s.delete(item.id));
        out.sent += 1;
      } catch (e) {
        if (e instanceof ApiError) {
          await tx("readwrite", (s) => s.put({ ...item, error: message(e) }));
          out.failed.push(`${item.label}: ${message(e)}`);
        } else {
          out.waiting = (await pending()).filter((p) => !p.error).length;
          break; // no signal: try again later
        }
      }
    }
    notify();
    return out;
  })().finally(() => {
    running = null;
  });
  return running;
}

if (typeof window !== "undefined") {
  window.addEventListener("online", () => void flush());
}
