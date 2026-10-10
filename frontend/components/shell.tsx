"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, Bell, CloudArrowUp, CloudCheck, CloudSlash, MagnifyingGlass, Warning } from "@phosphor-icons/react";
import { get, type S } from "@/lib/api";
import { flush, outboxState, subscribe, type OutboxState } from "@/lib/offline";
import { applyUpdate, isIos, isStandalone, onInstallable, onUpdateReady, promptInstall } from "@/lib/device";
import { dateTime } from "@/lib/api";

const timeOnly = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });

/** The outbox at a glance: waiting, sending, refused or all sent, with Sync now. */
export function SyncBadge({ compact = false }: { compact?: boolean }) {
  const [st, setSt] = useState<OutboxState | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const read = () => void outboxState().then(setSt);
    read();
    const off = subscribe(read);
    const t = setInterval(read, 15_000);
    return () => {
      off();
      clearInterval(t);
    };
  }, []);
  if (!st) return null;
  const tone = st.failed ? "bad" : st.uploading ? "accent" : st.waiting ? "warn" : "ok";
  const Icon = st.failed ? Warning : st.uploading ? CloudArrowUp : !st.online ? CloudSlash : st.waiting ? CloudArrowUp : CloudCheck;
  const words = st.failed
    ? `${st.failed} refused`
    : st.uploading
      ? "Sending"
      : st.waiting
        ? `${st.waiting} waiting${st.online ? "" : ", offline"}`
        : st.online
          ? "All sent"
          : "Offline";
  const last = st.lastSyncAt ? `Last sync ${timeOnly.format(new Date(st.lastSyncAt))}` : "Not synced yet";
  return (
    <span className={`sync-badge ${tone}`} role="status" aria-live="polite" title={last}>
      <Icon size={16} weight="bold" aria-hidden="true" />
      <span>{words}</span>
      {!compact && <span className="muted small sync-last">{last}</span>}
      {(st.waiting > 0 || st.failed > 0) && (
        <button
          type="button"
          className="btn small"
          disabled={busy || !st.online}
          onClick={async () => {
            setBusy(true);
            await flush().catch(() => null);
            setBusy(false);
          }}
        >
          Sync now
        </button>
      )}
    </span>
  );
}

/** Unread messages, polled once a minute and on focus. */
export function NotificationBell({ label = true }: { label?: boolean }) {
  const [n, setN] = useState(0);
  const load = useCallback(() => {
    get<S["UnreadOut"]>("/account/notifications/unread").then((r) => setN(r.unread), () => undefined);
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    const vis = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", vis);
    window.addEventListener("p1-inbox-changed", load);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", vis);
      window.removeEventListener("p1-inbox-changed", load);
    };
  }, [load]);
  return (
    <Link href="/notifications" className="bell" aria-label={`Messages, ${n} unread`}>
      <Bell size={20} weight={n ? "fill" : "regular"} aria-hidden="true" />
      {label && <span>Messages</span>}
      {n > 0 && <span className="count attention">{n > 99 ? "99+" : n}</span>}
    </Link>
  );
}

const KIND_WORD: Record<string, string> = {
  customer: "Customer",
  project: "Project",
  quote: "Quote",
  task: "Task",
  item: "Catalogue",
};

/** One box to find a customer, project, quote, task or catalogue item. Ctrl+K or / to focus. */
export function SearchBox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<S["SearchHitOut"][]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.("input, textarea, select, [contenteditable]");
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        box.current?.focus();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => {
    if (q.trim().length < 2) {
      setHits([]);
      return;
    }
    const t = setTimeout(() => {
      get<S["SearchHitOut"][]>(`/search?q=${encodeURIComponent(q.trim())}&limit=8`).then(
        (r) => {
          setHits(r);
          setActive(0);
        },
        () => setHits([]),
      );
    }, 220);
    return () => clearTimeout(t);
  }, [q]);
  function go(url: string) {
    setOpen(false);
    setQ("");
    router.push(url);
  }
  return (
    <div className="searchbox" role="search">
      <MagnifyingGlass size={16} aria-hidden="true" />
      <input
        ref={box}
        type="search"
        placeholder="Search customers, quotes, tasks"
        aria-label="Search"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, hits.length - 1));
          else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          else if (e.key === "Enter" && hits[active]) go(hits[active].url);
          else if (e.key === "Enter" && q.trim().length >= 2) go(`/search?q=${encodeURIComponent(q.trim())}`);
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && q.trim().length >= 2 && (
        <ul className="search-hits" role="listbox" aria-label="Search results">
          {hits.length === 0 ? (
            <li className="muted small">Nothing found yet. Try a code or part of a name.</li>
          ) : (
            hits.map((h, i) => (
              <li key={h.url + h.title} role="option" aria-selected={i === active}>
                <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => go(h.url)}>
                  <span className="muted small">{KIND_WORD[h.kind] ?? h.kind}</span>
                  <span className="title">{h.title}</span>
                  {h.subtitle && <span className="muted small">{h.subtitle}</span>}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

/** "New version ready": the new service worker waits until the person chooses to reload. */
export function UpdateBanner() {
  const [ready, setReady] = useState(false);
  useEffect(() => onUpdateReady(setReady), []);
  if (!ready) return null;
  return (
    <div className="update-banner" role="status">
      <span>A new version of Project One is ready.</span>
      <button className="btn small primary with-glyph" onClick={applyUpdate}>
        <ArrowClockwise size={16} aria-hidden="true" /> Reload
      </button>
    </div>
  );
}

/** Add the app to the home screen: the browser's own prompt on Android, the steps on iPhone. */
export function InstallCard() {
  const [can, setCan] = useState(false);
  const [hidden, setHidden] = useState(true);
  useEffect(() => {
    try {
      setHidden(localStorage.getItem("p1-install-hidden") === "1" || isStandalone());
    } catch {
      setHidden(isStandalone());
    }
    return onInstallable(setCan);
  }, []);
  const hide = () => {
    setHidden(true);
    try {
      localStorage.setItem("p1-install-hidden", "1");
    } catch {
      /* storage blocked */
    }
  };
  if (hidden || (!can && !isIos())) return null;
  return (
    <div className="install-card" role="note">
      <strong>Add Project One to your home screen</strong>
      {can ? (
        <span className="small">It opens full screen, works with weak signal and can show messages.</span>
      ) : (
        <span className="small">
          On iPhone: tap Share, then Add to Home Screen. Messages on iPhone arrive only once the app is added.
        </span>
      )}
      <span className="row">
        {can && (
          <button className="btn small primary" onClick={() => void promptInstall()}>
            Install the app
          </button>
        )}
        <button className="btn small quiet" onClick={hide}>
          Not now
        </button>
      </span>
    </div>
  );
}

/** Signs a phone out after a stretch without use, so a lost or shared phone does not stay open.
 * Saved work stays on the phone for its owner. */
export function useIdleLock(minutes: number, onIdle: () => void, enabled: boolean) {
  const last = useRef(Date.now());
  useEffect(() => {
    if (!enabled) return;
    const touch = () => {
      last.current = Date.now();
    };
    const events = ["pointerdown", "keydown", "touchstart", "scroll"];
    events.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const t = setInterval(() => {
      if (Date.now() - last.current > minutes * 60_000) onIdle();
    }, 30_000);
    const vis = () => {
      if (document.visibilityState === "visible" && Date.now() - last.current > minutes * 60_000) onIdle();
    };
    document.addEventListener("visibilitychange", vis);
    return () => {
      events.forEach((e) => window.removeEventListener(e, touch));
      clearInterval(t);
      document.removeEventListener("visibilitychange", vis);
    };
  }, [minutes, onIdle, enabled]);
}

export const lastSeen = (iso: string | null | undefined) => (iso ? dateTime(iso) : "never");
