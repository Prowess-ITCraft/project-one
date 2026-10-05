"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, message, post, resumeSession, type S } from "@/lib/api";
import { Field, Notice } from "@/components/ui";
import { CopyButton } from "@/components/kit";
import { forgetKept } from "@/lib/hooks";
import { Wordmark } from "@/components/field";
import {
  CalendarCheck,
  Certificate,
  Copy,
  Desktop,
  DeviceMobile,
  EnvelopeSimple,
  Eye,
  EyeSlash,
  FileText,
  Key,
  ListChecks,
  LockSimple,
  Question,
  Receipt,
  ShieldCheck,
  SignIn,
  Target,
  Warning,
  Wrench,
  type Icon,
} from "@phosphor-icons/react";

/** The steps every project walks, and who does each, drawn as the trace on the right. */
const PATH: { name: string; who: string; icon: Icon }[] = [
  { name: "Audit intake", who: "Audit engineer", icon: FileText },
  { name: "Current IT", who: "Solution architect", icon: Desktop },
  { name: "Ideal IT", who: "Solution architect", icon: Target },
  { name: "Gap analysis", who: "Solution architect", icon: ListChecks },
  { name: "Quotation", who: "Sales", icon: Receipt },
  { name: "Plan", who: "Project manager", icon: CalendarCheck },
  { name: "Field work", who: "Field engineers", icon: Wrench },
];

/** The round icon at the top of each sign-in step. */
function StepIcon({ icon: I }: { icon: Icon }) {
  return (
    <span className="signin-icon" aria-hidden="true">
      <I size={22} weight="duotone" />
    </span>
  );
}

type Step =
  | { kind: "password" }
  | { kind: "code"; token: string }
  | { kind: "enrol"; token: string; secret?: string; uri?: string; qr?: string }
  | { kind: "recovery"; codes: string[] };

/** The development login is offered only when the app runs on this computer. The account does
 * not exist outside development: `seed-demo` refuses to run in production. */
const DEMO = { email: "adi@test.com", password: "test1234" };
/** Where to go once signed in: the page the person was on when the sign-in ran out, if it is a
 * page of this app, otherwise the projects. */
function nextPage(): string {
  const n = typeof window === "undefined" ? "" : (new URLSearchParams(window.location.search).get("next") ?? "");
  return /^\/(?![/\\])/.test(n) && !n.startsWith("/login") ? n : "/projects";
}

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
  const [useRecovery, setUseRecovery] = useState(false);
  const [recovery, setRecovery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState(false);
  useEffect(() => setLocal(isLocal()), []);
  // Still signed in from earlier (the session lasts 14 days): no password or code needed.
  useEffect(() => {
    void resumeSession().then((ok) => ok && router.replace(nextPage()));
  }, [router]);

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
    router.replace(nextPage());
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
      const body = useRecovery ? { challenge_token: token, recovery_code: recovery.trim() } : { challenge_token: token, code };
      await post("/auth/mfa/verify", body, { cookieMode: true });
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
              <StepIcon icon={ShieldCheck} />
              <h1>Sign in</h1>
              <p className="lede">Use your ITCraft or IITPL work email.</p>
              <Field id="email" label="Work email">
                <div className="with-icon">
                  <EnvelopeSimple size={18} aria-hidden="true" />
                  <input
                    id="email"
                    type="email"
                    autoComplete="username"
                    placeholder="name@itcraft.net.in"
                    autoFocus
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </Field>
              <Field id="password" label="Password">
                <div className="with-icon with-action">
                  <LockSimple size={18} aria-hidden="true" />
                  <input
                    id="password"
                    type={show ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyUp={(e) => setCaps(e.getModifierState("CapsLock"))}
                  />
                  <button
                    type="button"
                    className="icon-btn"
                    aria-pressed={show}
                    aria-label={show ? "Hide password" : "Show password"}
                    title={show ? "Hide password" : "Show password"}
                    onClick={() => setShow(!show)}
                  >
                    {show ? <EyeSlash size={20} /> : <Eye size={20} />}
                  </button>
                </div>
                {caps && (
                  <span className="caps-warn">
                    <Warning size={15} weight="fill" aria-hidden="true" /> Caps Lock is on
                  </span>
                )}
              </Field>
              {error && <Notice tone="bad">{error}</Notice>}
              <button className="btn primary wide" disabled={busy}>
                <SignIn size={18} weight="bold" aria-hidden="true" />
                {busy ? "Signing in" : "Sign in"}
              </button>
              <p className="signin-help">
                <Question size={16} aria-hidden="true" />
                <span>Forgot your password or locked out? Your admin can unlock your account or set a new password.</span>
              </p>
            </form>
          )}

          {step.kind === "code" && (
            <form onSubmit={verify}>
              <StepIcon icon={useRecovery ? Key : DeviceMobile} />
              <h1>{useRecovery ? "Use a recovery code" : "Enter your code"}</h1>
              {useRecovery ? (
                <>
                  <p className="lede">Type one of the recovery codes you saved when you set up the authenticator. Each works once.</p>
                  <Field id="recovery" label="Recovery code" hint="For example ABCDE-FGH23" error={error}>
                    <input
                      id="recovery"
                      type="text"
                      className="mono"
                      autoComplete="off"
                      autoCapitalize="characters"
                      required
                      autoFocus
                      value={recovery}
                      onChange={(e) => setRecovery(e.target.value)}
                    />
                  </Field>
                </>
              ) : (
                <>
                  <p className="lede">Open your authenticator app and type the 6 digit code for Project One.</p>
                  <CodeInput value={code} onChange={setCode} label="6 digit code" error={error} />
                </>
              )}
              <div className="row">
                <button className="btn primary" disabled={busy || (useRecovery ? recovery.trim().length < 10 : code.length < 6)}>
                  {busy ? "Checking" : "Verify"}
                </button>
                {back}
              </div>
              <p className="signin-help">
                <button
                  type="button"
                  className="linklike"
                  onClick={() => {
                    setUseRecovery(!useRecovery);
                    setError("");
                  }}
                >
                  {useRecovery ? "Use the code from my app instead" : "Lost your phone? Use a recovery code"}
                </button>
              </p>
            </form>
          )}

          {step.kind === "enrol" && (
            <form onSubmit={confirmEnrol}>
              <StepIcon icon={DeviceMobile} />
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
              <StepIcon icon={Key} />
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
                <CopyButton
                  className="btn"
                  text={step.codes.join("\n")}
                  label="Copy codes"
                  icon={<Copy size={16} aria-hidden="true" />}
                />
                <button className="btn primary" onClick={finish}>
                  I saved them, continue
                </button>
              </div>
            </div>
          )}

          {local && step.kind === "password" && (
          <aside className="demo" aria-label="Development login">
            <Wrench size={20} aria-hidden="true" className="demo-icon" />
            <div>
              <strong>Development login</strong>
              <span className="muted small">
                {DEMO.email}, password {DEMO.password}. An admin, so the first sign-in sets up an authenticator.
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
        </div>
      </main>

      <aside className="signin-panel" aria-label="What Project One does">
        <p className="signin-claim">From the audit report to a signed certificate.</p>
        <ol className="circuit">
          {PATH.map(({ name, who, icon: I }) => (
            <li key={name}>
              <span className="station" aria-hidden="true">
                <I size={18} />
              </span>
              <span className="stop">
                {name}
                <small>{who}</small>
              </span>
            </li>
          ))}
          <li className="cert">
            <span className="station" aria-hidden="true">
              <Certificate size={20} weight="fill" />
            </span>
            <span className="stop">
              Certified by IITPL
              <small>Signed by the Director</small>
            </span>
            <img src="/brand/iitpl-logo.png" alt="International Infocom Technologies" width={112} height={72} />
          </li>
        </ol>
      </aside>
    </div>
  );
}
