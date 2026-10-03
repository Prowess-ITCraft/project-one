"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { date, get, message } from "@/lib/api";
import { AckForm, PublicFrame } from "@/components/public";
import { Notice, Skeleton } from "@/components/ui";

type View = {
  project_name: string;
  what: string;
  kind: string;
  reason: string;
  approved_by: string | null;
  expires_at: string;
  already_acknowledged: boolean;
};

/** The customer accepts that one item is left out of the certificate, by link. */
export default function WaiverAck() {
  const { token } = useParams<{ token: string }>();
  const [v, setV] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  useEffect(() => {
    get<View>(`/public/waivers/${token}`).then(setV).catch((e) => setError(message(e)));
  }, [token]);

  return (
    <PublicFrame>
      {error && <Notice tone="bad">{error}</Notice>}
      {!v && !error && <Skeleton lines={5} />}
      {v && (
        <>
          <p className="muted small">{v.project_name}</p>
          <h1>One item left out of the work</h1>
          <p className="lede">
            ITCraft proposes not to deliver the item below in this project. It will be listed as an exclusion on the completion report and the certificate.
          </p>
          <dl className="kv verify-kv">
            <dt>Item</dt>
            <dd>{v.what}</dd>
            <dt>Why</dt>
            <dd>
              {v.kind === "not applicable" ? "It does not apply to your site" : "You moved it to a later date"}. {v.reason}
            </dd>
            {v.approved_by && (
              <>
                <dt>Approved by</dt>
                <dd>{v.approved_by}, Director</dd>
              </>
            )}
          </dl>
          {done || v.already_acknowledged ? (
            <div className="verdict" data-tone="ok">
              <b>Accepted</b>
              <span>Thank you. ITCraft has your confirmation. You can close this page.</span>
            </div>
          ) : (
            <>
              <p className="muted small">If you do not agree, do not confirm; reply to the email instead. This link works until {date(v.expires_at)}.</p>
              <AckForm
                path={`/public/waivers/${token}`}
                confirmText="I accept that this item is left out and listed as an exclusion."
                onDone={() => setDone(true)}
              />
            </>
          )}
        </>
      )}
    </PublicFrame>
  );
}
