"use client";
import Link from "next/link";
import { useMe } from "@/lib/hooks";
import { Notice } from "@/components/ui";

const PAGES = [
  {
    href: "/settings/company",
    perm: "settings:edit",
    title: "Company and quotation",
    text: "Letterhead, GSTIN, terms, quote numbers, price validity and the minimum margin.",
  },
  {
    href: "/settings/templates",
    perm: "template:edit",
    title: "Templates",
    text: "What each audit finding turns into on a BOQ, and the steps and evidence of each field task.",
  },
  {
    href: "/settings/gates",
    perm: "gate:configure",
    title: "Stage approvals",
    text: "Who approves each of the eight stages, and which ones the customer acknowledges.",
  },
  {
    href: "/settings/certificate",
    perm: "certificate:settings",
    title: "Certificate",
    text: "The certificate wording and the IITPL stamp.",
  },
  {
    href: "/settings/switches",
    perm: "flags:manage",
    title: "Switches",
    text: "Turn parts of Project One on or off: customer codes, learning, customer sign-in.",
  },
];

export default function Settings() {
  const { can } = useMe();
  const mine = PAGES.filter((p) => can(p.perm));
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>How Project One works for the whole company. Every change is recorded in the audit log.</p>
        </div>
      </div>
      {mine.length === 0 ? (
        <Notice>There are no settings for your role.</Notice>
      ) : (
        <div className="settings-grid">
          {mine.map((p) => (
            <Link key={p.href} href={p.href}>
              <strong>{p.title}</strong>
              <span className="muted small">{p.text}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
