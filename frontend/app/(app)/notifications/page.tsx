"use client";
import Link from "next/link";
import { useState } from "react";
import { dateTime, post, type S } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { Empty, Notice, Skeleton, useAction } from "@/components/ui";

/** Every message sent to you, newest first: the notification centre. */
export default function Messages() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const list = useData<S["InboxItemOut"][]>(`/account/notifications?limit=100${unreadOnly ? "&unread_only=true" : ""}`);
  const { busy, run } = useAction();
  const changed = () => {
    window.dispatchEvent(new Event("p1-inbox-changed"));
    void list.reload();
  };
  async function read(ids: string[], all = false) {
    await run(() => post("/account/notifications/read", { ids, all }));
    changed();
  }
  const items = list.data ?? [];
  const unread = items.filter((n) => !n.read_at).length;
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Messages</h1>
          <p>
            What Project One told you, newest first. Choose which messages come by email, here and to your
            phone in <Link href="/account#messages">your settings</Link>.
          </p>
        </div>
        <div className="row">
          <label className="check">
            <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
            Unread only
          </label>
          <button className="btn" disabled={busy || unread === 0} onClick={() => void read([], true)}>
            Mark all read
          </button>
        </div>
      </div>
      {list.error && <Notice tone="bad">{list.error}</Notice>}
      {list.loading && !list.data && <Skeleton lines={6} />}
      {list.data && items.length === 0 && (
        <Empty title={unreadOnly ? "Nothing unread" : "No messages yet"}>
          Task changes, work to verify and quotes about to expire show up here.
        </Empty>
      )}
      {items.length > 0 && (
        <ul className="inbox">
          {items.map((n) => (
            <li key={n.id} data-unread={!n.read_at}>
              <span className="subject">
                {!n.read_at && <span className="unread-dot" aria-label="Unread" />}
                {n.link ? (
                  <Link href={n.link} onClick={() => !n.read_at && void read([n.id])}>
                    {n.subject}
                  </Link>
                ) : (
                  n.subject
                )}
              </span>
              <span className="muted small">{dateTime(n.created_at)}</span>
              <span className="body">{n.body.replace(/^Hello [^\n]*\n+/, "").trim()}</span>
              {!n.read_at && (
                <span>
                  <button className="btn quiet small" disabled={busy} onClick={() => void read([n.id])}>
                    Mark read
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
