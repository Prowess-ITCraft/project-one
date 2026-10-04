"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { post, type S } from "@/lib/api";
import { forgetKept, MeProvider, ToastHost, useData } from "@/lib/hooks";
import { Skeleton, roleLabel } from "@/components/ui";
import { Logo, Wordmark } from "@/components/field";
import { notePage } from "@/components/kit";
import {
  Books,
  Brain,
  Certificate,
  CircleHalf,
  ClipboardText,
  FolderSimple,
  Moon,
  Package,
  Question,
  SealCheck,
  SignOut,
  SquaresFour,
  Sun,
  UsersThree,
  type Icon,
} from "@phosphor-icons/react";

const NAV: { href: string; label: string; perm: string | null; icon: Icon }[] = [
  { href: "/field", label: "My tasks", perm: "field:work", icon: ClipboardText },
  { href: "/dashboard", label: "Dashboard", perm: "dashboard:read", icon: SquaresFour },
  { href: "/review", label: "Review", perm: "field:verify", icon: SealCheck },
  { href: "/projects", label: "Projects", perm: "project:read", icon: FolderSimple },
  { href: "/catalogue", label: "Catalogue", perm: "catalogue:read", icon: Package },
  { href: "/library", label: "Library", perm: "dataset:read", icon: Books },
  { href: "/learning", label: "Learning", perm: "ml:read", icon: Brain },
  { href: "/users", label: "Accounts", perm: "user:manage", icon: UsersThree },
  { href: "/settings/certificate", label: "Certificate", perm: "certificate:settings", icon: Certificate },
  { href: "/help", label: "Help", perm: null, icon: Question },
];

/** A one-line pointer to the guide, until the person opens it or hides the hint. */
function GuideHint({ path }: { path: string }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    try {
      setShow(localStorage.getItem("p1-guide-seen") !== "1");
    } catch {
      /* storage blocked: no hint */
    }
  }, []);
  function seen() {
    setShow(false);
    try {
      localStorage.setItem("p1-guide-seen", "1");
    } catch {
      /* storage blocked */
    }
  }
  useEffect(() => {
    if (path.startsWith("/help")) seen();
  }, [path]);
  if (!show) return null;
  return (
    <div className="guide-hint" role="note">
      <span>New to Project One? The guide shows your part, step by step, in about five minutes.</span>
      <span className="row">
        <Link className="btn small primary" href="/help">
          Open the guide
        </Link>
        <button className="btn quiet small" onClick={seen}>
          Hide
        </button>
      </span>
    </div>
  );
}

function ThemeSwitch() {
  const [t, setT] = useState<string>("system");
  useEffect(() => {
    try {
      setT(localStorage.getItem("p1-theme") ?? "system");
    } catch {
      /* storage blocked: stay on the system theme */
    }
  }, []);
  function next() {
    const n = t === "system" ? "light" : t === "light" ? "dark" : "system";
    setT(n);
    try {
      if (n === "system") {
        localStorage.removeItem("p1-theme");
        delete document.documentElement.dataset.theme;
      } else {
        localStorage.setItem("p1-theme", n);
        document.documentElement.dataset.theme = n;
      }
    } catch {
      /* storage blocked: the change lasts until reload */
    }
  }
  const ThemeIcon = t === "light" ? Sun : t === "dark" ? Moon : CircleHalf;
  return (
    <button className="btn quiet small with-glyph" onClick={next} aria-label={`Theme is ${t}. Change theme`}>
      <ThemeIcon size={16} aria-hidden="true" />
      Theme: {t === "system" ? "match device" : t}
    </button>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { data: me, error } = useData<S["MeOut"]>("/auth/me");
  // Field engineers start on their own tasks, not on the project list.
  const engineerOnly = !!me && me.roles.length === 1 && me.roles[0] === "field_engineer";
  useEffect(() => {
    if (engineerOnly && path === "/projects") router.replace("/field");
  }, [engineerOnly, path, router]);
  // Back buttons go back only to pages opened inside the app.
  useEffect(() => notePage(path), [path]);
  // Installed app on phones (public/sw.js). Not in development, where it would cache hot reloads.
  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* the app works without it, only not offline */
      });
    }
  }, []);

  if (error && !me) {
    return (
      <main className="auth">
        <div>
          <h1>We could not load your account</h1>
          <p className="lede">{error}</p>
          <Link className="btn primary" href="/login">
            Sign in again
          </Link>
        </div>
      </main>
    );
  }
  if (!me) {
    return (
      <div className="main" style={{ maxWidth: 560 }}>
        <Skeleton lines={6} />
      </div>
    );
  }
  const perms = new Set(me.permissions);
  const can = (p: string) => perms.has(p);

  async function signOut() {
    try {
      await post("/auth/logout");
    } catch {
      /* already signed out */
    }
    forgetKept();
    router.replace("/login");
  }

  return (
    <MeProvider value={{ me, can }}>
      <ToastHost>
        <div className="shell">
          <aside className="side">
            <Link href={engineerOnly ? "/field" : "/projects"} className="brand">
              <Logo size={30} />
              <span className="words">
                Project One
                <small>
                  <Wordmark />
                </small>
              </span>
            </Link>
            <nav className="nav" aria-label="Main">
              {NAV.filter((n) => !n.perm || can(n.perm)).map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={path.startsWith(n.href) ? "page" : undefined}
                >
                  <n.icon size={18} weight={path.startsWith(n.href) ? "fill" : "regular"} aria-hidden="true" />
                  {n.label}
                </Link>
              ))}
            </nav>
            <div className="side-foot">
              <div className="who small">
                <span className="avatar" aria-hidden="true">
                  {me.full_name
                    .split(/\s+/)
                    .map((w) => w[0])
                    .join("")
                    .slice(0, 2)
                    .toUpperCase()}
                </span>
                <span>
                  <span className="who-name">{me.full_name}</span>
                  <span className="muted">{me.roles.map(roleLabel).join(", ")}</span>
                </span>
              </div>
              <ThemeSwitch />
              <button className="btn quiet small with-glyph" onClick={signOut}>
                <SignOut size={16} aria-hidden="true" />
                Sign out
              </button>
            </div>
          </aside>
          <div className="main">
            <div className="page">
              <GuideHint path={path} />
              {children}
            </div>
          </div>
        </div>
      </ToastHost>
    </MeProvider>
  );
}
