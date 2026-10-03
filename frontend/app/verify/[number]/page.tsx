"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, get, message } from "@/lib/api";
import { PublicFrame } from "@/components/public";
import { Skeleton } from "@/components/ui";

type Public = {
  number: string;
  status: "valid" | "revoked";
  intact: boolean;
  customer: string;
  project: string;
  issued_on: string;
  director: string;
  scope: string[];
  exclusions: string[];
  work_finished: string | null;
  fingerprint: string;
  revoked_on: string | null;
};

export default function VerifyCertificate() {
  const { number } = useParams<{ number: string }>();
  const [c, setC] = useState<Public | null>(null);
  const [error, setError] = useState<{ unknown: boolean; text: string } | null>(null);
  useEffect(() => {
    get<Public>(`/public/certificates/${encodeURIComponent(number)}`)
      .then(setC)
      .catch((e) => setError({ unknown: e instanceof ApiError && e.status === 404, text: message(e) }));
  }, [number]);

  const verdict = !c
    ? null
    : !c.intact
      ? { tone: "bad", head: "Do not rely on this certificate", body: "Its record no longer matches what was signed. Contact IITPL." }
      : c.status === "revoked"
        ? { tone: "bad", head: "Revoked", body: `IITPL withdrew this certificate on ${c.revoked_on}. It is no longer valid.` }
        : { tone: "ok", head: "Genuine and valid", body: `Signed by ${c.director}, Director, IITPL, on ${c.issued_on}.` };

  return (
    <PublicFrame>
      <p className="muted small">Certificate check</p>
      <h1 className="mono verify-number">{decodeURIComponent(number)}</h1>
      {!c && !error && <Skeleton lines={5} />}
      {error && (
        <div className="verdict" data-tone="bad">
          <b>{error.unknown ? "No certificate has this number" : "Could not check right now"}</b>
          <span>{error.unknown ? "Check the number against the printed certificate. A genuine one is always listed here." : error.text}</span>
        </div>
      )}
      {c && verdict && (
        <>
          <div className="verdict" data-tone={verdict.tone}>
            <b>{verdict.head}</b>
            <span>{verdict.body}</span>
          </div>
          <dl className="kv verify-kv">
            <dt>Customer</dt>
            <dd>{c.customer}</dd>
            <dt>Project</dt>
            <dd>{c.project}</dd>
            {c.work_finished && (
              <>
                <dt>Work finished</dt>
                <dd>{c.work_finished}</dd>
              </>
            )}
            <dt>Fingerprint</dt>
            <dd className="mono">{c.fingerprint}</dd>
          </dl>
          <h2>Work delivered and verified</h2>
          <ul className="verify-scope">
            {c.scope.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          {c.exclusions.length > 0 && (
            <>
              <h2>Excluded by agreement with the customer</h2>
              <ul className="verify-scope">
                {c.exclusions.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small">The fingerprint printed under the QR code must match the one above.</p>
        </>
      )}
    </PublicFrame>
  );
}
