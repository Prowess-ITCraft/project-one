"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { post, type S } from "@/lib/api";
import { forgetKept, MeProvider, ToastHost, useData } from "@/lib/hooks";
import { Skeleton } from "@/components/ui";
import { Logo, Wordmark } from "@/components/field";

const NAV = [
  { href: "/field", label: "My tasks", perm: "field:work" },
  { href: "/review", label: "Review", perm: "field:verify" },
  { href: "/dashboard", label: "Dashboard", perm: "dashboard:read" },
  { href: "/projects", label: "Projects", perm: "project:read" },
  { href: "/catalogue", label: "Catalogue", perm: "catalogue:read" },
  { href: "/library", label: "Library", perm: "dataset:read" },
  { href: "/learning", label: "Learning", perm: "ml:read" },
  { href: "/users", label: "Users", perm: "user:manage" },
  { href: "/settings/certificate", label: "Certificate", perm: "certificate:settings" },
];

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
  return (
    <button className="btn quiet small" onClick={next} aria-label={`Theme is ${t}. Change theme`}>
      Theme: {t}
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
              {NAV.filter((n) => can(n.perm)).map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={path.startsWith(n.href) ? "page" : undefined}
                >
                  {n.label}
                </Link>
              ))}
            </nav>
            <div className="side-foot">
              <div className="small">
                <div>{me.full_name}</div>
                <div className="muted">{me.roles.map((r) => r.replace(/_/g, " ")).join(", ")}</div>
              </div>
              <ThemeSwitch />
              <button className="btn quiet small" onClick={signOut}>
                Sign out
              </button>
            </div>
          </aside>
          <div className="main">
            <div className="page">{children}</div>
          </div>
        </div>
      </ToastHost>
    </MeProvider>
  );
}
