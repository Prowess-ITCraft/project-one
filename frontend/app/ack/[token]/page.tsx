"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { date, get, message } from "@/lib/api";
import { AckForm, PublicFrame } from "@/components/public";
import { Notice, Skeleton } from "@/components/ui";

type View = {
  customer_name: string;
  project_name: string;
  stage_label: string;
  contact_name: string;
  expires_at: string;
  already_acknowledged: boolean;
};

/** A customer contact confirms a project stage from the single-use link ITCraft sent them. */
export default function StageAck() {
  const { token } = useParams<{ token: string }>();
  const [v, setV] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  useEffect(() => {
    get<View>(`/public/acks/${token}`).then(setV).catch((e) => setError(message(e)));
  }, [token]);

  return (
    <PublicFrame>
      {error && <Notice tone="bad">{error}</Notice>}
      {!v && !error && <Skeleton lines={5} />}
      {v && (
        <>
          <p className="muted small">{v.customer_name}</p>
          <h1>{v.project_name}</h1>
          <p className="lede">
            ITCraft asks you, {v.contact_name}, to confirm the stage <b>{v.stage_label}</b>.
          </p>
          {done || v.already_acknowledged ? (
            <div className="verdict" data-tone="ok">
              <b>Confirmed</b>
              <span>Thank you. ITCraft has your confirmation. You can close this page.</span>
            </div>
          ) : (
            <>
              <p className="muted small">This link works once and until {date(v.expires_at)}.</p>
              <AckForm
                path={`/public/acks/${token}`}
                expectName={v.contact_name}
                confirmText={`I confirm the ${v.stage_label} stage for ${v.project_name}.`}
                onDone={() => setDone(true)}
              />
            </>
          )}
        </>
      )}
    </PublicFrame>
  );
}
