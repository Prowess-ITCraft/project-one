import type { components } from "./schema";

export type S = components["schemas"];

/** Error shape from the API (RFC 9457 problem+json). `code` is stable, `detail` is for people. */
export class ApiError extends Error {
  status: number;
  code: string;
  fields: { loc: (string | number)[]; msg: string }[];
  constructor(status: number, code: string, detail: string, fields: ApiError["fields"] = []) {
    super(detail);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

const BASE = "/api/v1";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function cookie(name: string): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : "";
}

export function newKey(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

type Opts = { idem?: boolean; form?: FormData; noRefresh?: boolean; cookieMode?: boolean };

let refreshing: Promise<boolean> | null = null;
async function refresh(): Promise<boolean> {
  refreshing ??= fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "X-Auth-Mode": "cookie", "X-CSRF-Token": cookie("p1_csrf") },
  })
    .then(async (r) => {
      // Always read the body: an unread response stays open in the browser.
      const body = await r.json().catch(() => null);
      if (r.ok) return true;
      // Another tab renewed the session a moment ago; its new cookies are already ours.
      return body?.code === "refresh_race";
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

// The sign-in steps themselves never trigger a renewal. Everything else does, including
// /auth/me, which every page asks first: the short sign-in cookie lasts 15 minutes and the
// renewal keeps people signed in for 14 days without the password or the code.
const NO_RENEWAL = ["/auth/login", "/auth/mfa", "/auth/refresh", "/auth/logout"];

/** True when the browser still holds a session, renewing the short cookie if it has to. The
 * sign-in page uses it so a returning person goes straight in. */
export async function resumeSession(): Promise<boolean> {
  const me = () =>
    fetch(`${BASE}/auth/me`)
      .then(async (r) => {
        await r.arrayBuffer(); // read it, so the response does not stay open
        return r.ok;
      })
      .catch(() => false);
  if (await me()) return true;
  return (await refresh()) && (await me());
}

export async function api<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  opts: Opts = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.cookieMode) headers["X-Auth-Mode"] = "cookie";
  if (UNSAFE.has(method)) headers["X-CSRF-Token"] = cookie("p1_csrf");
  if (opts.idem) headers["Idempotency-Key"] = newKey();
  let payload: BodyInit | undefined;
  if (opts.form) payload = opts.form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  if (res.status === 401 && !opts.noRefresh && !NO_RENEWAL.some((p) => path.startsWith(p))) {
    if (await refresh()) return api<T>(method, path, body, { ...opts, noRefresh: true });
    if (typeof window !== "undefined") window.location.href = "/login";
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    throw new ApiError(
      res.status,
      data?.code ?? "error",
      data?.detail ?? "Something went wrong. Try again.",
      data?.errors ?? [],
    );
  }
  return data as T;
}

export const get = <T>(p: string) => api<T>("GET", p);
export const post = <T>(p: string, b?: unknown, o?: Opts) => api<T>("POST", p, b, o);
export const put = <T>(p: string, b?: unknown, o?: Opts) => api<T>("PUT", p, b, o);
export const patch = <T>(p: string, b?: unknown, o?: Opts) => api<T>("PATCH", p, b, o);
export const del = <T>(p: string) => api<T>("DELETE", p);

/** Plain message for a failed call, including the first field error when there is one. */
export function message(e: unknown): string {
  if (e instanceof ApiError) {
    const f = e.fields[0];
    return f ? `${e.message} ${f.loc.slice(1).join(".")}: ${f.msg}` : e.message;
  }
  return "Could not reach the server. Check your connection and try again.";
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
export const money = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "Not set" : inr.format(Number(v));
export const date = (v: string | null | undefined) =>
  v
    ? new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeZone: "Asia/Kolkata" }).format(
        new Date(v),
      )
    : "";
export const dateTime = (v: string | null | undefined) =>
  v
    ? new Intl.DateTimeFormat("en-IN", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Asia/Kolkata",
      }).format(new Date(v))
    : "";
