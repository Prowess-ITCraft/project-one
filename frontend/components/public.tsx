"use client";
import { useState } from "react";
import { message, post } from "@/lib/api";
import { Logo, Wordmark } from "@/components/field";
import { Field, Notice } from "@/components/ui";

/** The frame for pages anyone with a link can open: no navigation, no account. */
export function PublicFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="public">
      <header className="public-head">
        <Logo size={28} />
        <Wordmark />
      </header>
      <main className="public-main">{children}</main>
      <footer className="public-foot muted small">ITCraft, an IITPL company. This page shows only what the link holder needs.</footer>
    </div>
  );
}

/** Type your name and confirm. Used for stage sign-off and for waivers. */
export function AckForm({
  path,
  expectName,
  confirmText,
  onDone,
}: {
  path: string;
  expectName?: string;
  confirmText: string;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="stack"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await post(path, { full_name: name.trim(), accept: true });
          onDone();
        } catch (err) {
          setError(message(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <Field
        id="ack-name"
        label="Your full name"
        hint={expectName ? `Type it as ITCraft has it: ${expectName}.` : "As it appears on your company records."}
      >
        <input id="ack-name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <label className="check">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        {confirmText}
      </label>
      {error && <Notice tone="bad">{error}</Notice>}
      <div>
        <button className="btn primary" disabled={busy || !agree || name.trim().length < 2}>
          {busy ? "Confirming" : "Confirm"}
        </button>
      </div>
    </form>
  );
}
