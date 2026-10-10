"use client";
/**
 * The phone side of the installed app: the service worker and its updates, the install prompt,
 * Web Push, location and photo stamps, and wiping what the phone keeps when someone signs out.
 */
import { api } from "./api";

// ------------------------------------------------------------------ service worker and updates

type Waiting = { worker: ServiceWorker } | null;
let waiting: Waiting = null;
const updateListeners = new Set<(ready: boolean) => void>();

export function onUpdateReady(fn: (ready: boolean) => void): () => void {
  updateListeners.add(fn);
  fn(!!waiting);
  return () => updateListeners.delete(fn);
}

function announce(worker: ServiceWorker) {
  waiting = { worker };
  updateListeners.forEach((l) => l(true));
}

/** Register the service worker. A new build gets a new worker URL (the build id), so the phone
 * notices; the new worker waits until the person chooses "Reload" rather than swapping the app
 * under someone in the middle of a task. */
export function registerServiceWorker() {
  if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
  const build = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";
  navigator.serviceWorker
    .register(`/sw.js?v=${encodeURIComponent(build)}`)
    .then((reg) => {
      if (reg.waiting && navigator.serviceWorker.controller) announce(reg.waiting);
      reg.addEventListener("updatefound", () => {
        const w = reg.installing;
        w?.addEventListener("statechange", () => {
          if (w.state === "installed" && navigator.serviceWorker.controller) announce(w);
        });
      });
      // Look for a new version when the app comes back to the front.
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") void reg.update().catch(() => undefined);
      });
    })
    .catch(() => {
      /* the app works without it, only not offline */
    });
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return;
    reloading = true;
    window.location.reload();
  });
}

export function applyUpdate() {
  if (waiting) waiting.worker.postMessage({ type: "p1-skip-waiting" });
  else window.location.reload();
}

// ------------------------------------------------------------------ install prompt

type InstallEvent = Event & { prompt(): Promise<void>; userChoice: Promise<{ outcome: string }> };
let deferred: InstallEvent | null = null;
const installListeners = new Set<(can: boolean) => void>();

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as InstallEvent;
    installListeners.forEach((l) => l(true));
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    installListeners.forEach((l) => l(false));
  });
}

export function onInstallable(fn: (can: boolean) => void): () => void {
  installListeners.add(fn);
  fn(!!deferred);
  return () => installListeners.delete(fn);
}

export async function promptInstall(): Promise<boolean> {
  if (!deferred) return false;
  await deferred.prompt();
  const { outcome } = await deferred.userChoice;
  deferred = null;
  installListeners.forEach((l) => l(false));
  return outcome === "accepted";
}

export const isIos = () =>
  typeof navigator !== "undefined" && /iPhone|iPad|iPod/.test(navigator.userAgent);

export const isStandalone = () =>
  typeof window !== "undefined" &&
  (window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true);

// ------------------------------------------------------------------ Web Push

function keyBytes(base64url: string): Uint8Array {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export const pushSupported = () =>
  typeof window !== "undefined" &&
  "serviceWorker" in navigator &&
  "PushManager" in window &&
  "Notification" in window;

export async function currentPushEndpoint(): Promise<string | null> {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  return sub?.endpoint ?? null;
}

/** Ask permission, subscribe this browser and give the subscription to the server. */
export async function enablePush(publicKey: string): Promise<"on" | "denied" | "unsupported"> {
  if (!pushSupported()) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";
  const reg = await navigator.serviceWorker.ready;
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(publicKey) as BufferSource,
    }));
  const json = sub.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
  await api("POST", "/account/push/subscriptions", {
    endpoint: json.endpoint,
    keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
    user_agent: navigator.userAgent.slice(0, 200),
  });
  return "on";
}

/** Stop push to this browser: tell the server, then unsubscribe here. */
export async function disablePush(): Promise<void> {
  if (!pushSupported()) return;
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await api("POST", "/account/push/subscriptions/remove", { endpoint: sub.endpoint }).catch(() => undefined);
  await sub.unsubscribe().catch(() => undefined);
}

// ------------------------------------------------------------------ sign-out wipe

/** What a shared or lost phone must not keep after sign-out: cached pages and push to this
 * device. Saved, unsent field work stays (it belongs to its owner and is sent when they sign in
 * again); the sign-out screen says so before it happens. */
export async function wipeDevice(): Promise<void> {
  await disablePush().catch(() => undefined);
  if (typeof caches !== "undefined") {
    const keys = await caches.keys().catch(() => [] as string[]);
    await Promise.all(keys.filter((k) => k.startsWith("p1-")).map((k) => caches.delete(k)));
  }
}

// ------------------------------------------------------------------ location and photo stamps

export type Located = { lat: number; lng: number; accuracy_m: number };
export type LocationResult = { ok: true; at: Located } | { ok: false; reason: string };

/** The phone's location. `precise` waits longer for a GPS fix (check-in needs one). */
export function locate(precise = false): Promise<LocationResult> {
  return new Promise((resolve) => {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      resolve({ ok: false, reason: "This browser cannot share a location" });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) =>
        resolve({
          ok: true,
          at: {
            lat: Number(p.coords.latitude.toFixed(6)),
            lng: Number(p.coords.longitude.toFixed(6)),
            accuracy_m: Math.round(p.coords.accuracy),
          },
        }),
      (err) =>
        resolve({
          ok: false,
          reason:
            err.code === err.PERMISSION_DENIED
              ? "Location permission denied"
              : err.code === err.TIMEOUT
                ? "No GPS fix in time"
                : "Location not available",
        }),
      { enableHighAccuracy: precise, timeout: precise ? 15_000 : 6_000, maximumAge: precise ? 120_000 : 600_000 },
    );
  });
}

const stampTime = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

/** A copy of a photo with the time, place and task drawn along the bottom. The original file
 * is kept and sent as the evidence; the server records its own time and the file's hash, which
 * count. Null when the browser cannot draw the image (the original still goes). */
export async function stampPhoto(
  file: File,
  lines: { task: string; where: LocationResult },
): Promise<Blob | null> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close?.();
    const size = Math.max(14, Math.round(w / 45));
    const place = lines.where.ok
      ? `${lines.where.at.lat.toFixed(5)}, ${lines.where.at.lng.toFixed(5)} (within ${lines.where.at.accuracy_m} m)`
      : lines.where.reason;
    const text = [`${lines.task}`, `${stampTime.format(new Date())} IST, ${place}`];
    const band = size * 1.5 * text.length + size;
    ctx.fillStyle = "rgba(15, 42, 69, 0.78)";
    ctx.fillRect(0, h - band, w, band);
    ctx.fillStyle = "#ffffff";
    ctx.font = `600 ${size}px system-ui, sans-serif`;
    text.forEach((t, i) => ctx.fillText(t, size * 0.75, h - band + size * 1.4 * (i + 1)));
    return await new Promise((resolve) => canvas.toBlob((b) => resolve(b), "image/jpeg", 0.82));
  } catch {
    return null;
  }
}
