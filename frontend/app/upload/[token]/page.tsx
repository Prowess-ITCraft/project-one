"use client";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { CheckCircle, UploadSimple } from "@phosphor-icons/react";
import { api, dateTime, message, type S } from "@/lib/api";
import { Logo, Wordmark } from "@/components/field";

/** A single-use link from a field engineer: upload one configuration export from any browser
 * (for example a laptop on the customer's network). No sign-in; the link works once and only
 * for a few minutes. */
export default function UploadWithLink() {
  const { token } = useParams<{ token: string }>();
  const [info, setInfo] = useState<S["UploadLinkInfoOut"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<S["UploadLinkDoneOut"] | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    api<S["UploadLinkInfoOut"]>("GET", `/public/field-upload/${token}`, undefined, { noRefresh: true }).then(setInfo, (e) => setError(message(e)));
  }, [token]);

  async function send(file: File) {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      setDone(await api<S["UploadLinkDoneOut"]>("POST", `/public/field-upload/${token}`, undefined, { form, noRefresh: true }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="upload-page">
      <div className="row">
        <Logo size={30} />
        <strong>
          Project One <Wordmark />
        </strong>
      </div>
      {done ? (
        <div className="section stack">
          <h1 className="row">
            <CheckCircle size={28} weight="fill" color="var(--ok)" aria-hidden="true" /> Received
          </h1>
          <p>
            <span className="mono">{done.file_name}</span> is now on the task. The engineer sees it on their phone. This link
            cannot be used again.
          </p>
          {done.parse && <p className="parse-result">{String(done.parse.message ?? "")}</p>}
          <p className="muted small">You can close this page.</p>
        </div>
      ) : info ? (
        <div className="section stack">
          <h1>Upload the configuration export</h1>
          <p>
            For task <span className="mono">{info.task_ref}</span> {info.title}
            {info.asset ? (
              <>
                {" "}
                on <span className="mono">{info.asset}</span>
              </>
            ) : null}
            {info.project ? `, ${info.project}` : ""}.
          </p>
          <p className="muted">{info.label}</p>
          <input
            ref={input}
            type="file"
            hidden
            accept={info.accept}
            aria-label="Configuration export"
            onChange={(e) => e.target.files?.[0] && void send(e.target.files[0])}
          />
          <div>
            <button className="btn primary big with-glyph" disabled={busy} onClick={() => input.current?.click()}>
              <UploadSimple size={18} aria-hidden="true" /> {busy ? "Uploading" : "Choose the file"}
            </button>
          </div>
          <p className="muted small">The link works once, until {dateTime(info.expires_at)}.</p>
          {error && (
            <p className="notice bad" role="alert">
              {error}
            </p>
          )}
        </div>
      ) : error ? (
        <div className="section stack">
          <h1>This link cannot be used</h1>
          <p>{error}</p>
        </div>
      ) : (
        <p className="muted">Checking the link</p>
      )}
    </main>
  );
}
