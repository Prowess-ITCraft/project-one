"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { post, type S } from "@/lib/api";
import { forgetKept, MeProvider, ToastHost, useData } from "@/lib/hooks";
import { flush, pending, setOutboxUser } from "@/lib/offline";
import { registerServiceWorker, wipeDevice } from "@/lib/device";
import { Skeleton, roleLabel } from "@/components/ui";
import { Logo, Wordmark } from "@/components/field";
import { notePage } from "@/components/kit";
import { InstallCard, NotificationBell, SearchBox, SyncBadge, UpdateBanner, useIdleLock } from "@/components/shell";
import {
  Bell,
  Books,
  Brain,
  Buildings,
  Certificate,
  CircleHalf,
  ClipboardText,
  FolderSimple,
  Gear,
  Moon,
  Package,
  Question,
  SealCheck,
  SignOut,
  SquaresFour,
  Sun,
  UserCircle,
  UsersThree,
  type Icon,
} from "@phosphor-icons/react";

type NavItem = { href: string; label: string; perm: string | null; icon: Icon; any?: string[] };

const NAV: NavItem[] = [
  { href: "/field", label: "My tasks", perm: "field:work", icon: ClipboardText },
  { href: "/dashboard", label: "Dashboard", perm: "dashboard:read", icon: SquaresFour },
  { href: "/review", label: "Review", perm: "field:verify", icon: SealCheck },
  { href: "/projects", label: "Projects", perm: "project:read", icon: FolderSimple },
  { href: "/customers", label: "Customers", perm: "customer:read", icon: Buildings },
  { href: "/catalogue", label: "Catalogue", perm: "catalogue:read", icon: Package },
  { href: "/library", label: "Library", perm: "dataset:read", icon: Books },
  { href: "/learning", label: "Learning", perm: "ml:read", icon: Brain },
  { href: "/users", label: "Accounts", perm: "user:manage", icon: UsersThree },
  {
    href: "/settings",
    label: "Settings",
    perm: null,
    any: ["settings:edit", "template:edit", "gate:configure", "certificate:settings"],
    icon: Gear,
  },
  { href: "/help", label: "Help", perm: null, icon: Question },
];

// Field engineers have their own phone layout and only these pages (ADR 0027).
const FIELD_PAGES = ["/field", "/notifications", "/account", "/help", "/search"];
const FIELD_IDLE_MINUTES = 15;

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

function UnsentNote({ count, onStay, onLeave }: { count: number; onStay: () => void; onLeave: () => void }) {
  return (
    <div className="outbox-note stack" role="alert">
      <span>
        {count} action{count === 1 ? " is" : "s are"} saved on this phone and not sent yet. They stay on the
        phone and are sent when you next sign in here; nobody else can send them for you.
      </span>
      <span className="row">
        <button className="btn small primary" onClick={onStay}>
          Stay signed in
        </button>
        <button className="btn small quiet" onClick={onLeave}>
          Sign out anyway
        </button>
      </span>
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { data: me, error } = useData<S["MeOut"]>("/auth/me");
  // Field work saved on this phone and not sent yet, found when signing out.
  const [unsent, setUnsent] = useState(0);
  const engineerOnly = !!me && me.roles.length === 1 && me.roles[0] === "field_engineer";

  // Route guard: a field engineer stays in the field app.
  useEffect(() => {
    if (engineerOnly && !FIELD_PAGES.some((p) => path === p || path.startsWith(`${p}/`))) router.replace("/field");
  }, [engineerOnly, path, router]);
  // Back buttons go back only to pages opened inside the app.
  useEffect(() => notePage(path), [path]);
  // Installed app on phones (public/sw.js). Not in development, where it would cache hot reloads.
  useEffect(() => registerServiceWorker(), []);
  // Saved field work belongs to the person who saved it.
  useEffect(() => {
    if (me) setOutboxUser(me.id, me.permissions.includes("field:work"));
    return () => setOutboxUser(null);
  }, [me]);

  const signOut = useCallback(
    async (anyway = false, reason?: string) => {
      if (!anyway) {
        // Phones get shared, and only the person who saved the work can send it. Send it now if
        // there is signal; otherwise say so before signing out.
        await flush().catch(() => null);
        const left = (await pending().catch(() => [])).length;
        if (left) {
          setUnsent(left);
          return;
        }
      }
      setUnsent(0);
      await wipeDevice().catch(() => undefined);
      try {
        await post("/auth/logout");
      } catch {
        /* already signed out */
      }
      forgetKept();
      setOutboxUser(null);
      router.replace(reason ? `/login?reason=${reason}` : "/login");
    },
    [router],
  );
  const idle = useCallback(() => void signOut(true, "idle"), [signOut]);
  useIdleLock(FIELD_IDLE_MINUTES, idle, engineerOnly);
  // The account page signs out through the shell, which knows about unsent field work.
  useEffect(() => {
    const h = () => void signOut();
    window.addEventListener("p1-sign-out", h);
    return () => window.removeEventListener("p1-sign-out", h);
  }, [signOut]);

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
  const initials = me.full_name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  if (engineerOnly) {
    const tab = (href: string) => (path === href || path.startsWith(`${href}/`) ? "page" : undefined);
    return (
      <MeProvider value={{ me, can }}>
        <ToastHost>
          <div className="field-shell">
            <header className="field-top">
              <Link href="/field" className="brand" aria-label="My tasks">
                <Logo size={26} />
                <span className="words">Project One</span>
              </Link>
              <SyncBadge compact />
            </header>
            <main className="field-main">
              <UpdateBanner />
              {unsent > 0 && <UnsentNote count={unsent} onStay={() => setUnsent(0)} onLeave={() => void signOut(true)} />}
              <InstallCard />
              {children}
            </main>
            <nav className="bottom-nav" aria-label="Main">
              <Link href="/field" aria-current={tab("/field")}>
                <ClipboardText size={22} weight={tab("/field") ? "fill" : "regular"} aria-hidden="true" />
                Tasks
              </Link>
              <Link href="/notifications" aria-current={tab("/notifications")}>
                <Bell size={22} weight={tab("/notifications") ? "fill" : "regular"} aria-hidden="true" />
                Messages
              </Link>
              <Link href="/account" aria-current={tab("/account")}>
                <UserCircle size={22} weight={tab("/account") ? "fill" : "regular"} aria-hidden="true" />
                Me
              </Link>
              <Link href="/help" aria-current={tab("/help")}>
                <Question size={22} weight={tab("/help") ? "fill" : "regular"} aria-hidden="true" />
                Help
              </Link>
            </nav>
          </div>
        </ToastHost>
      </MeProvider>
    );
  }

  return (
    <MeProvider value={{ me, can }}>
      <ToastHost>
        <div className="shell">
          <aside className="side">
            <Link href="/projects" className="brand">
              <Logo size={30} />
              <span className="words">
                Project One
                <small>
                  <Wordmark />
                </small>
              </span>
            </Link>
            <nav className="nav" aria-label="Main">
              {NAV.filter((n) => (!n.perm || can(n.perm)) && (!n.any || n.any.some(can))).map((n) => (
                <Link key={n.href} href={n.href} aria-current={path.startsWith(n.href) ? "page" : undefined}>
                  <n.icon size={18} weight={path.startsWith(n.href) ? "fill" : "regular"} aria-hidden="true" />
                  {n.label}
                </Link>
              ))}
            </nav>
            <div className="side-foot">
              <NotificationBell />
              <Link href="/account" className="who small" aria-label="My account">
                <span className="avatar" aria-hidden="true">
                  {initials}
                </span>
                <span>
                  <span className="who-name">{me.full_name}</span>
                  <span className="muted">{me.roles.map(roleLabel).join(", ")}</span>
                </span>
              </Link>
              <ThemeSwitch />
              <button className="btn quiet small with-glyph" onClick={() => void signOut()}>
                <SignOut size={16} aria-hidden="true" />
                Sign out
              </button>
            </div>
          </aside>
          <div className="main">
            <div className="page">
              <div className="topline">
                <SearchBox />
                {can("field:work") && <SyncBadge compact />}
              </div>
              <UpdateBanner />
              {unsent > 0 && <UnsentNote count={unsent} onStay={() => setUnsent(0)} onLeave={() => void signOut(true)} />}
              <GuideHint path={path} />
              {children}
            </div>
          </div>
        </div>
      </ToastHost>
    </MeProvider>
  );
}
