"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ApiError, get, message, passing, type S } from "./api";

// What an engineer needs to reopen a task with no signal: who they are and their field work.
// Field responses never carry prices. Cleared on sign-out (forgetKept), since phones get shared.
const KEEP = /^\/(auth\/me$|field\/)/;
const KEPT = "p1-kept:";

function keep(path: string, data: unknown, at: number) {
  if (!KEEP.test(path)) return;
  try {
    localStorage.setItem(KEPT + path, JSON.stringify({ at, data }));
  } catch {
    /* storage full or blocked: the page still works online */
  }
}

function kept<T>(path: string): { at: number; data: T } | null {
  if (!KEEP.test(path)) return null;
  try {
    const raw = localStorage.getItem(KEPT + path);
    if (!raw) return null;
    const v = JSON.parse(raw) as { at?: unknown; data?: T };
    // copies kept before the time was stored count as very old
    return typeof v.at === "number" && "data" in v ? { at: v.at, data: v.data as T } : { at: 0, data: v as T };
  } catch {
    return null;
  }
}

export function forgetKept() {
  try {
    for (const k of Object.keys(localStorage)) if (k.startsWith(KEPT)) localStorage.removeItem(k);
  } catch {
    /* nothing kept */
  }
}

/** Load data once and on demand. Keeps the last good data while reloading. With no network,
 * field pages fall back to what they last loaded and say so through `stale`. `at` is when the
 * data shown was asked of the server (ms), so a page can lay newer local changes over it. */
export function useData<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [at, setAt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(path !== null);
  const seq = useRef(0);
  const shown = useRef(false);
  const load = useCallback(async () => {
    if (path === null) return;
    const n = ++seq.current;
    const asked = Date.now();
    setLoading(true);
    try {
      const d = await get<T>(path);
      if (n === seq.current) {
        shown.current = true;
        setData(d);
        setAt(asked);
        setError(null);
        setStale(false);
        keep(path, d, asked);
      }
    } catch (e) {
      if (n !== seq.current) return;
      const old = passing(e) && !(e instanceof ApiError && e.status === 401) ? kept<T>(path) : null;
      if (old !== null) {
        // keep what is on screen; only an empty page takes the kept copy
        if (!shown.current) {
          shown.current = true;
          setData(old.data);
          setAt(old.at);
        }
        setStale(true);
      } else setError(message(e));
    } finally {
      if (n === seq.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    load();
  }, [load]);
  return { data, at, error, stale, loading, reload: load };
}

type Me = S["MeOut"];
const MeCtx = createContext<{ me: Me; can: (p: string) => boolean } | null>(null);
export const MeProvider = MeCtx.Provider;
export function useMe() {
  const v = useContext(MeCtx);
  if (!v) throw new Error("useMe outside the app shell");
  return v;
}

type Toast = { id: number; text: string; bad?: boolean };
const ToastCtx = createContext<(text: string, bad?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastHost({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, bad?: boolean) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, bad }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), bad ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={t.bad ? "toast bad" : "toast"}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
