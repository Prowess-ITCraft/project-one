"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, message, post, type S } from "@/lib/api";
import { Field, Notice } from "@/components/ui";
import { forgetKept } from "@/lib/hooks";
import { Wordmark } from "@/components/field";

/** The eight stages every project walks, drawn as the circuit on the right. */
const PATH = [
  "Audit intake",
  "Current IT",
  "Ideal IT",
  "Gap analysis",
  "Quotation",
  "Plan",
  "Field work",
] as const;

type Step =
  | { kind: "password" }
  | { kind: "code"; token: string }
  | { kind: "enrol"; token: string; secret?: string; uri?: string; qr?: string }
  | { kind: "recovery"; codes: string[] };

/** The development login is offered only when the app runs on this computer. The account does
 * not exist outside development: `seed-demo` refuses to run in production. */
const DEMO = { email: "adi@test.com", password: "test1234" };
const isLocal = () =>
  typeof window !== "undefined" && ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);

function CodeInput({ value, onChange, label, error }: { value: string; onChange: (v: string) => void; label: string; error?: string }) {
  return (
    <Field id="code" label={label} error={error}>
      <input
        id="code"
        className="code-input"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        required
        autoFocus
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))}
      />
    </Field>
  );
}

export default function Login() {
  const router = useRouter();
  const [step, setStep] = useState<Step>({ kind: "password" });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState(false);
  useEffect(() => setLocal(isLocal()), []);

  async function go(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setError("Too many attempts. Wait a minute and try again.");
      } else {
        setError(message(e));
      }
    } finally {
      setBusy(false);
    }
  }

  const finish = () => {
    forgetKept(); // a shared phone must not show the last person's tasks offline
    router.replace("/projects");
  };

  const signIn = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!email.trim() || !password) {
      setError(!email.trim() ? "Enter your work email." : "Enter your password.");
      return;
    }
    go(async () => {
      const r = await post<S["TokenOut"] | S["ChallengeOut"]>("/auth/login", { email, password }, { cookieMode: true });
      if (r.status === "authenticated") return finish();
      setCode("");
      setStep(r.status === "mfa_required" ? { kind: "code", token: r.challenge_token } : { kind: "enrol", token: r.challenge_token });
    });
  };

  const verify = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (step.kind !== "code") return;
    const token = step.token;
    go(async () => {
      await post("/auth/mfa/verify", { challenge_token: token, code }, { cookieMode: true });
      finish();
    });
  };

  const startEnrol = () => {
    if (step.kind !== "enrol") return;
    const token = step.token;
    go(async () => {
      const r = await post<S["MfaEnrolStartOut"]>("/auth/mfa/enrol/start", { enrol_token: token });
      setStep({ kind: "enrol", token, secret: r.secret, uri: r.otpauth_uri, qr: r.qr_svg });
    });
  };

  const confirmEnrol = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (step.kind !== "enrol") return;
    const token = step.token;
    go(async () => {
      const r = await post<S["MfaEnrolConfirmOut"]>("/auth/mfa/enrol/confirm", { enrol_token: token, code }, { cookieMode: true });
      setStep({ kind: "recovery", codes: r.recovery_codes });
    });
  };

  const back = (
    <button
      type="button"
      className="btn quiet"
      onClick={() => {
        setError("");
        setStep({ kind: "password" });
      }}
    >
      Back
    </button>
  );

  return (
    <div className="signin">
      <main className="signin-form">
        <div className="signin-brand">
          <img src="/brand/itcraft-logo-icon.svg" alt="" width={44} height={38} />
          <span>
            Project One
            <small>
              <Wordmark />
            </small>
          </span>
        </div>

        <div className="signin-body">
          {step.kind === "password" && (
            <form onSubmit={signIn} noValidate>
              <h1>Sign in</h1>
              <p className="lede">Use your ITCraft work email.</p>
              <Field id="email" label="Work email">
                <input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field id="password" label="Password" hint={caps ? "Caps Lock is on." : undefined}>
                <div className="with-action">
                  <input
                    id="password"
                    type={show ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyUp={(e) => setCaps(e.getModifierState("CapsLock"))}
                  />
                  <button type="button" className="btn quiet small" aria-pressed={show} onClick={() => setShow(!show)}>
                    {show ? "Hide" : "Show"}
                  </button>
                </div>
              </Field>
              {error && <Notice tone="bad">{error}</Notice>}
              <button className="btn primary wide" disabled={busy}>
                {busy ? "Signing in" : "Sign in"}
              </button>
              <p className="signin-help">Locked out or forgot your password? Ask your Admin to unlock your account.</p>
            </form>
          )}

          {step.kind === "code" && (
            <form onSubmit={verify}>
              <h1>Enter your code</h1>
              <p className="lede">Open your authenticator app and type the 6 digit code for Project One.</p>
              <CodeInput value={code} onChange={setCode} label="6 digit code" error={error} />
              <div className="row">
                <button className="btn primary" disabled={busy || code.length < 6}>
                  {busy ? "Checking" : "Verify"}
                </button>
                {back}
              </div>
            </form>
          )}

          {step.kind === "enrol" && (
            <form onSubmit={confirmEnrol}>
              <h1>Set up your authenticator</h1>
              <p className="lede">Your role needs a second step at sign-in. It takes about a minute, once.</p>
              {!step.secret ? (
                <>
                  <ol className="enrol-steps">
                    <li>Install Google Authenticator or Microsoft Authenticator on your phone.</li>
                    <li>Scan the code shown on the next screen.</li>
                    <li>Type the 6 digit code the app shows.</li>
                  </ol>
                  {error && <Notice tone="bad">{error}</Notice>}
                  <div className="row">
                    <button type="button" className="btn primary" onClick={startEnrol} disabled={busy}>
                      Show my code
                    </button>
                    {back}
                  </div>
                </>
              ) : (
                <>
                  <div className="enrol-qr">
                    {step.qr && <img src={step.qr} alt="QR code to add Project One to your authenticator app" width={168} height={168} />}
                    <div>
                      <p>Scan this with your authenticator app.</p>
                      <p className="muted small">No camera? Add an account by key:</p>
                      <code className="codeblock enrol-key">{step.secret}</code>
                      <p className="muted small">
                        On the phone itself, <a href={step.uri}>add it with one tap</a>.
                      </p>
                    </div>
                  </div>
                  <CodeInput value={code} onChange={setCode} label="Code the app shows" error={error} />
                  <button className="btn primary wide" disabled={busy || code.length < 6}>
                    {busy ? "Checking" : "Confirm and continue"}
                  </button>
                </>
              )}
            </form>
          )}

          {step.kind === "recovery" && (
            <div>
              <h1>Save your recovery codes</h1>
              <p className="lede">
                Each code works once if you lose your phone. They are shown only now, so store them somewhere safe.
              </p>
              <div className="codeblock recovery">
                {step.codes.map((c) => (
                  <div key={c}>{c}</div>
                ))}
              </div>
              <div className="row">
                <button
                  type="button"
                  className="btn"
                  onClick={() => void navigator.clipboard?.writeText(step.codes.join("\n"))}
                >
                  Copy codes
                </button>
                <button className="btn primary" onClick={finish}>
                  I saved them, continue
                </button>
              </div>
            </div>
          )}
        </div>

        {local && step.kind === "password" && (
          <aside className="demo" aria-label="Development login">
            <div>
              <strong>Development login</strong>
              <span className="muted small">
                {DEMO.email} with password {DEMO.password}. Admin, so the first sign-in sets up an authenticator.
              </span>
            </div>
            <button
              type="button"
              className="btn small"
              onClick={() => {
                setEmail(DEMO.email);
                setPassword(DEMO.password);
              }}
            >
              Fill in
            </button>
          </aside>
        )}
      </main>

      <aside className="signin-panel" aria-hidden="true">
        <p className="signin-claim">From the audit report to a signed certificate.</p>
        <ol className="circuit">
          {PATH.map((name, i) => (
            <li key={name} style={{ "--i": i } as React.CSSProperties}>
              {name}
            </li>
          ))}
          <li className="cert" style={{ "--i": PATH.length } as React.CSSProperties}>
            <span>Certified by IITPL</span>
            <img src="/brand/iitpl-logo.png" alt="" width={124} height={80} />
          </li>
        </ol>
      </aside>
    </div>
  );
}
