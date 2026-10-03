"use client";
import Link from "next/link";
import { dateTime, type S } from "@/lib/api";
import { useData, useMe } from "@/lib/hooks";
import { Badge, Empty, Notice, Skeleton } from "@/components/ui";

export default function ReviewQueue() {
  const { can } = useMe();
  const q = useData<S["RunOut"][]>(can("field:verify") ? "/field/review-queue" : null);
  if (!can("field:verify")) return <Notice tone="warn">Only verifiers can open the review queue.</Notice>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review</h1>
          <p>
            Work the customer has accepted and the configuration check passed. Approve it to close the task, or send it
            back with what must be fixed. Your own work never appears here.
          </p>
        </div>
      </div>
      {q.error && <Notice tone="bad">{q.error}</Notice>}
      {q.loading && !q.data && <Skeleton lines={5} />}
      {q.data && q.data.length === 0 && (
        <Empty title="Nothing waiting for review">Handed over tasks arrive here, oldest first.</Empty>
      )}
      {q.data && q.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Task</th>
              <th>Device</th>
              <th>Sent back</th>
              <th className="right">Handed over</th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((r) => (
              <tr key={r.id}>
                <td data-label="Task">
                  <Link href={`/field/${r.id}`} className="title">
                    <span className="mono">{r.task_ref}</span> {r.title}
                  </Link>
                </td>
                <td data-label="Device">{r.asset ?? "None"}</td>
                <td data-label="Sent back">{r.rework_count ? <Badge tone="warn">{r.rework_count} time(s)</Badge> : "Never"}</td>
                <td className="right" data-label="Handed over">
                  {dateTime(r.handed_over_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
