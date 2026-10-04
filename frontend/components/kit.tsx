"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ArrowLeft } from "@phosphor-icons/react";

/** Pages opened inside the app since it loaded. The shell counts them, so Back knows whether the
 * previous page is ours (go back) or not (a shared link or a new tab: go to the section). */
let pagesSeen = 0;
let lastPath = "";
export function notePage(path: string) {
  if (path === lastPath) return; // the same page reported twice (React runs effects twice in dev)
  lastPath = path;
  pagesSeen += 1;
}

/** "Back" plus the section it belongs to, at the top of every inner page. */
export function Back({ href, label }: { href: string; label: string }) {
  const router = useRouter();
  return (
    <nav className="backbar" aria-label="Back">
      <button
        type="button"
        className="btn small back"
        onClick={() => (pagesSeen > 1 ? router.back() : router.push(href))}
      >
        <ArrowLeft size={16} weight="bold" aria-hidden="true" /> Back
      </button>
      <span className="muted small">
        in <Link href={href}>{label}</Link>
      </span>
    </nav>
  );
}

/** Horizontal tabs. Keeps its state in the URL hash so a tab can be linked and survives reload. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string; count?: number | string; attention?: boolean }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}>
          {t.label}
          {t.count !== undefined && t.count !== 0 && (
            <span className={`count${t.attention ? " attention" : ""}`}>{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/** Side panel for editing one thing without leaving the page. Closes on Escape. */
export function Drawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <>
      <div className="drawer-back" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="row between">
          <h2>{title}</h2>
          <button className="btn quiet small" onClick={onClose}>
            Close
          </button>
        </div>
        {children}
      </aside>
    </>
  );
}

export function Check({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: ReactNode;
}) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

/** Split a comma or line separated text box into a clean list. */
export const toList = (s: string) =>
  s
    .split(/[\n,]/)
    .map((x) => x.trim())
    .filter(Boolean);
