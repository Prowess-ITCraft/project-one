"use client";
import { useEffect, useState } from "react";
import { dateTime, del, post, put, type S } from "@/lib/api";
import { useData, useMe, useToast } from "@/lib/hooks";
import { Badge, Field, Notice, Skeleton, roleLabel, useAction } from "@/components/ui";
import { ConfirmButton } from "@/components/kit";
import {
  currentPushEndpoint,
  disablePush,
  enablePush,
  isIos,
  isStandalone,
  onInstallable,
  promptInstall,
  pushSupported,
} from "@/lib/device";

const CHANNELS: { id: "email" | "in_app" | "push"; label: string }[] = [
  { id: "email", label: "Email" },
  { id: "in_app", label: "Messages page" },
  { id: "push", label: "Phone" },
];

function Password() {
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const { busy, run } = useAction();
  const mismatch = again.length > 0 && again !== next;
  return (
    <form
      className="section stack"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(() => post("/auth/password", { current_password: cur, new_password: next }));
        if (ok !== undefined) {
          toast("Password changed. Other devices are signed out.");
          setCur("");
          setNext("");
          setAgain("");
        }
      }}
    >
      <h2>Password</h2>
      <div className="form-grid">
        <Field id="pw-cur" label="Current password">
          <input id="pw-cur" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
        </Field>
        <Field id="pw-new" label="New password" hint="At least 12 characters. A short sentence works well.">
          <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Field id="pw-again" label="New password again" error={mismatch ? "The two new passwords differ." : undefined}>
          <input id="pw-again" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
        </Field>
      </div>
      <div>
        <button className="btn primary" disabled={busy || !cur || next.length < 12 || next !== again}>
          Change password
        </button>
      </div>
    </form>
  );
}

function Sessions() {
  const list = useData<S["SessionOut"][]>("/auth/sessions");
  const { busy, run } = useAction();
  return (
    <div className="section stack">
      <div className="row between">
        <h2>Where you are signed in</h2>
        <ConfirmButton
          question="Sign out every other device?"
          confirmLabel="Sign them out"
          disabled={busy || (list.data ?? []).filter((s) => !s.current).length === 0}
          onConfirm={async () => {
            await run(() => post("/auth/sessions/revoke-others"), "Other devices signed out");
            void list.reload();
          }}
        >
          Sign out other devices
        </ConfirmButton>
      </div>
      {list.error && <Notice tone="bad">{list.error}</Notice>}
      {!list.data ? (
        <Skeleton lines={3} />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Device</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.data.map((s) => (
              <tr key={s.id}>
                <td data-label="Device">
                  {(s.user_agent ?? "Unknown device").slice(0, 80)} {s.current && <Badge tone="ok">This device</Badge>}
                  <div className="muted small">{s.ip ?? ""}</div>
                </td>
                <td data-label="Last used">{dateTime(s.last_used_at)}</td>
                <td>
                  {!s.current && (
                    <button
                      className="btn quiet small"
                      disabled={busy}
                      onClick={async () => {
                        await run(() => del(`/auth/sessions/${s.id}`), "Signed out");
                        void list.reload();
                      }}
                    >
                      Sign out
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Preferences() {
  const prefs = useData<S["PrefOut"][]>("/account/notification-preferences");
  const { run } = useAction();
  async function set(template: string, channel: string, enabled: boolean) {
    await run(() => put(`/account/notification-preferences/${template}`, { enabled, channel }));
    void prefs.reload();
  }
  return (
    <div className="section stack" id="messages">
      <h2>Messages</h2>
      <p className="muted">
        Choose how each kind of message reaches you. Messages about work you must act on cannot be switched off.
      </p>
      {!prefs.data ? (
        <Skeleton lines={5} />
      ) : (
        <div className="table-scroll">
          <table className="table prefs">
            <thead>
              <tr>
                <th>Message</th>
                {CHANNELS.map((c) => (
                  <th key={c.id}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {prefs.data.map((p) => (
                <tr key={p.template}>
                  <td>
                    {p.label}
                    {!p.optional && <div className="muted small">Always sent</div>}
                  </td>
                  {CHANNELS.map((c) => (
                    <td key={c.id}>
                      <input
                        type="checkbox"
                        aria-label={`${p.label} by ${c.label}`}
                        checked={p.channels[c.id] ?? true}
                        disabled={!p.optional}
                        onChange={(e) => void set(p.template, c.id, e.target.checked)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ThisDevice() {
  const status = useData<S["PushStatusOut"]>("/account/push");
  const [endpoint, setEndpoint] = useState<string | null | undefined>(undefined);
  const [installable, setInstallable] = useState(false);
  const { busy, run } = useAction();
  const toast = useToast();
  useEffect(() => {
    void currentPushEndpoint().then(setEndpoint);
    return onInstallable(setInstallable);
  }, []);
  const ios = isIos();
  const installed = isStandalone();
  return (
    <div className="section stack">
      <h2>This phone or browser</h2>
      {!status.data ? (
        <Skeleton lines={2} />
      ) : !status.data.enabled ? (
        <Notice>Messages to phones are not set up on this server yet. Email and the Messages page still work.</Notice>
      ) : !pushSupported() ? (
        <Notice tone="warn">
          {ios && !installed
            ? "On iPhone, messages arrive only in the installed app. Tap Share, then Add to Home Screen, open it from there and come back here."
            : "This browser cannot receive messages."}
        </Notice>
      ) : endpoint ? (
        <div className="stack">
          <p>
            <Badge tone="ok">On</Badge> Messages come to this device. {status.data.devices} device
            {status.data.devices === 1 ? "" : "s"} in all.
          </p>
          <div className="row">
            <button
              className="btn"
              disabled={busy}
              onClick={() => void run(() => post("/account/push/test"), "Test message sent. It should arrive in a few seconds.")}
            >
              Send a test message
            </button>
            <button
              className="btn quiet"
              disabled={busy}
              onClick={async () => {
                await run(() => disablePush(), "Messages to this device stopped");
                setEndpoint(null);
                void status.reload();
              }}
            >
              Stop messages here
            </button>
          </div>
        </div>
      ) : (
        <div className="stack">
          <p className="muted">Get a message on this device when a task changes or work waits for you.</p>
          <div>
            <button
              className="btn primary"
              disabled={busy}
              onClick={async () => {
                const r = await run(() => enablePush(status.data?.public_key ?? ""));
                if (r === "denied") toast("Messages were blocked. Allow notifications for this site in the browser settings.", true);
                if (r === "unsupported") toast("This browser cannot receive messages.", true);
                setEndpoint(await currentPushEndpoint());
                void status.reload();
              }}
            >
              Get messages on this device
            </button>
          </div>
        </div>
      )}
      {!installed && (installable || ios) && (
        <div className="stack">
          <h3>Install the app</h3>
          {installable ? (
            <div>
              <button className="btn" onClick={() => void promptInstall()}>
                Add to home screen
              </button>
            </div>
          ) : (
            <p className="muted">On iPhone: tap Share, then Add to Home Screen.</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function Account() {
  const { me } = useMe();
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>My account</h1>
          <p>Your details, password, devices and how messages reach you.</p>
        </div>
      </div>
      <div className="section">
        <dl className="kv">
          <dt>Name</dt>
          <dd>{me.full_name}</dd>
          <dt>Email</dt>
          <dd>{me.email}</dd>
          <dt>Roles</dt>
          <dd>{me.roles.map(roleLabel).join(", ")}</dd>
          <dt>Authenticator</dt>
          <dd>{me.mfa_enabled ? "Set up" : "Not set up"}</dd>
        </dl>
        <p className="muted small">An Admin or the Director changes names and roles.</p>
      </div>
      <ThisDevice />
      <Preferences />
      <Password />
      <Sessions />
      <div className="section">
        <button className="btn" onClick={() => window.dispatchEvent(new Event("p1-sign-out"))}>
          Sign out
        </button>
      </div>
    </div>
  );
}
