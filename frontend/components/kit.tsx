"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft } from "@phosphor-icons/react";
import { openDoc } from "@/lib/api";

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

/** A link to an API document (PDF, Excel, HTML preview) that renews the sign-in before the
 * browser fetches it. Ctrl or middle click still opens it the plain way. */
export function DocLink({
  href,
  newTab,
  className,
  children,
}: {
  href: string;
  newTab?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a
      className={className}
      href={href}
      target={newTab ? "_blank" : undefined}
      rel={newTab ? "noreferrer" : undefined}
      onClick={(e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        openDoc(href, newTab);
      }}
    >
      {children}
    </a>
  );
}

/** Put text on the clipboard. The clipboard API works only over HTTPS; on a plain HTTP office
 * address the older copy command still does. False when neither worked. */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* refused: try the older way */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

/** A Copy button that says whether it worked. */
export function CopyButton({
  text,
  label = "Copy",
  className = "btn quiet small",
  icon,
}: {
  text: string;
  label?: string;
  className?: string;
  icon?: ReactNode;
}) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  return (
    <button type="button" className={className} onClick={async () => setState((await copyText(text)) ? "done" : "failed")}>
      {icon}
      {state === "done" ? "Copied" : state === "failed" ? "Could not copy, select it by hand" : label}
    </button>
  );
}

/** A button for something hard to undo: the first click asks, the second does it. */
export function ConfirmButton({
  question,
  confirmLabel,
  onConfirm,
  disabled,
  className = "btn",
  confirmClassName = "btn danger small",
  children,
}: {
  question: string;
  confirmLabel: string;
  onConfirm: () => unknown;
  disabled?: boolean;
  className?: string;
  /** Red by default; a step forward rather than a loss can use the primary style. */
  confirmClassName?: string;
  children: ReactNode;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button type="button" className={className} disabled={disabled} onClick={() => setAsking(true)}>
        {children}
      </button>
    );
  }
  return (
    <span className="row" role="group" aria-label={question}>
      <span className="small">{question}</span>
      <button
        type="button"
        className={confirmClassName}
        disabled={disabled}
        onClick={async () => {
          setAsking(false);
          await onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button type="button" className="btn quiet small" onClick={() => setAsking(false)}>
        Cancel
      </button>
    </span>
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
