"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { useMe } from "@/lib/hooks";
import {
  CalendarCheck,
  ClipboardText,
  Certificate,
  FileText,
  ListChecks,
  Receipt,
  Stack,
  Wrench,
  type Icon,
} from "@phosphor-icons/react";

/** The in-app guide. Plain steps per role, using the same words as the buttons on screen. */

const JOURNEY: { step: string; who: string; what: string; icon: Icon }[] = [
  { step: "Audit intake", who: "Audit engineer", what: "Upload the PrismSuite audit report and check what was read from it.", icon: FileText },
  { step: "Questionnaire", who: "Audit engineer", what: "Answer the questions the report cannot: budget, priorities, what the customer wants.", icon: ClipboardText },
  { step: "Infrastructure", who: "Solution architect", what: "Confirm the current IT and agree the ideal IT for this customer.", icon: Stack },
  { step: "Gaps", who: "Solution architect", what: "The difference between current and ideal, as a list of gaps to close.", icon: ListChecks },
  { step: "BOQ", who: "Sales", what: "The bill of quantities and the quotation, drafted from the gaps and priced from the catalogue.", icon: Receipt },
  { step: "Plan", who: "Project manager", what: "Turn the accepted BOQ into tasks, dates and engineers.", icon: CalendarCheck },
  { step: "Field work", who: "Field engineers, Technical lead", what: "Engineers do each task on site; the technical lead verifies it.", icon: Wrench },
  { step: "Completion", who: "Project manager, Director", what: "Lock the completion report; the Director signs the certificate.", icon: Certificate },
];

const ROLE_SECTIONS: { role: string; title: string; steps: ReactNode[] }[] = [
  {
    role: "sales_manager",
    title: "Sales",
    steps: [
      <>Open <b>Projects</b> and choose <b>New project</b>. Pick the customer, or add a new one.</>,
      <>For a quick BOQ, open the project and choose <b>Upload report and draft BOQ</b> on the Overview. Pick the PrismSuite report, answer five questions and the estimate appears with PDF and Excel downloads. It is marked "Not approved" and is not saved.</>,
      <>Prices come only from the price book. Enter or refresh them by hand under <b>Catalogue</b>: open an item and choose <b>Enter a new price</b>. Lines without a price stay blank until you do.</>,
      <>When the gaps are approved, use <b>Draft the BOQ from the gap register</b>. Adjust lines with <b>Add from catalogue</b> or <b>Add by hand</b>.</>,
      <>Download the quotation as PDF or Excel from the BOQ tab, then submit the stage for approval.</>,
    ],
  },
  {
    role: "sales_head",
    title: "Sales head",
    steps: [
      <>Check the BOQ lines and prices on the <b>BOQ</b> tab, then choose <b>Approve pricing</b>.</>,
      <>Approve or send back stages the sales team submitted. Someone else always approves what a person submitted.</>,
    ],
  },
  {
    role: "audit_engineer",
    title: "Audit engineer",
    steps: [
      <>Open the project, go to <b>Audit intake</b>, choose the PrismSuite Word or JSON file and select <b>Upload and import</b>. Or use <b>Upload report and draft BOQ</b> on the Overview to see the BOQ estimate straight away.</>,
      <>Read what was imported. Where the report disagrees with itself, pick the right value. Then approve the import.</>,
      <>Fill in the <b>Questionnaire</b> tab and choose <b>Save questionnaire</b>.</>,
      <>At the top of the project, pick the locked output and choose <b>Submit for approval</b>.</>,
    ],
  },
  {
    role: "solution_architect",
    title: "Solution architect",
    steps: [
      <>On <b>Infrastructure</b>, confirm the current IT and the ideal IT. Each is submitted for approval like any other stage.</>,
      <>On <b>Gaps</b>, review the gaps found between the two. Use <b>Add a gap by hand</b> for anything the rules missed, then submit.</>,
    ],
  },
  {
    role: "project_manager",
    title: "Project manager",
    steps: [
      <>On <b>Plan</b>, choose <b>Draft the plan</b> to turn the accepted BOQ into tasks, then <b>Schedule the plan</b> to set dates and engineers.</>,
      <>Check the plan and choose <b>Lock the plan</b>. Engineers see their tasks under <b>My tasks</b>.</>,
      <>Follow progress on <b>Field work</b>. If a task cannot be done, use <b>Ask for a waiver</b> on <b>Completion</b>; the Director decides and the customer acknowledges it.</>,
      <>When field work is finished, choose <b>Lock the report</b> on <b>Completion</b>.</>,
    ],
  },
  {
    role: "field_engineer",
    title: "Field engineer (on your phone)",
    steps: [
      <>Open <b>My tasks</b>. <b>Needs you</b> lists what you can do now, with the customer and project on each task.</>,
      <>Open a task and choose <b>Accept task</b>.</>,
      <>On site, add the arrival photo and choose <b>Check in</b>. When the work is checked, show the customer and choose <b>Confirm hand over</b>.</>,
      <>Work through <b>Before you change anything</b> and the <b>Steps</b>. Record <b>What the device shows</b> and add photos under <b>Evidence</b>.</>,
      <>Choose <b>Send for the check</b>. If a setting does not match, the page says which; fix it and send again.</>,
      <>Finish with <b>Hand over to the customer</b>. The technical lead then verifies your work.</>,
      <>Stuck? Choose <b>I cannot continue</b> and say what stops you. The task is marked blocked and your project manager sees it straight away.</>,
      <>No signal? Keep working. The app saves your steps on the phone and sends them by itself when the signal is back. If the server refuses one, the task says why: fix it and choose <b>Try again</b>, or <b>Remove</b> it.</>,
      <>Sign out only when everything is sent. If something is still on the phone, the app says so first; only you can send it, the next time you sign in on that phone.</>,
    ],
  },
  {
    role: "technical_lead",
    title: "Technical lead / verifier",
    steps: [
      <>Open <b>Review</b> to see tasks waiting for you.</>,
      <>Open a task, compare <b>Target</b> and <b>Found</b> for each setting, and look at the evidence.</>,
      <>Choose <b>Approve and close</b>, or <b>Send back</b> with what must be fixed. You never verify your own work.</>,
    ],
  },
  {
    role: "director",
    title: "Director",
    steps: [
      <><b>Dashboard</b> shows every active project: stage, field progress, blocked work and open issues.</>,
      <>Decide waivers on a project's <b>Completion</b> tab: <b>Approve</b> or <b>Turn down</b>.</>,
      <>When every condition on <b>Completion</b> is met, choose <b>Sign the certificate</b>. It carries your name and the IITPL stamp, and a QR code anyone can scan to check it.</>,
      <>Set the certificate wording and upload the stamp under <b>Certificate</b> in the sidebar.</>,
      <>You can also do everything an admin does: add people and give them roles under <b>Accounts</b>, as in the Admin steps.</>,
    ],
  },
  {
    role: "admin",
    title: "Admin",
    steps: [
      <>Open <b>Accounts</b> and choose <b>New account</b>. Fill in the name and email, tick one or more roles, and keep the strong password filled in for you.</>,
      <>Give the person their email and temporary password in person. Directors and admins set up an authenticator at first sign-in.</>,
      <>Click a name to change roles or details, <b>Reset password</b>, <b>Reset authenticator</b> (a lost phone), <b>Unlock</b>, or <b>Deactivate account</b> when someone leaves. Their history stays.</>,
      <>
        For developers and other systems: the API reference, where every call can be tried, is at{" "}
        <a href="/docs" target="_blank" rel="noreferrer">
          /docs
        </a>
        . The full list of routes is in <code>docs/API_ROUTES.md</code> in the project.
      </>,
    ],
  },
];

const GLOSSARY: [string, string][] = [
  ["PrismSuite report", "The audit of the customer's IT, as a Word or JSON file. Everything starts from it."],
  ["Stage", "One step of a project (see the list above). Each is submitted by one person and approved by another."],
  ["Gap", "Something the customer's IT is missing compared with the ideal."],
  ["BOQ", "Bill of quantities: the products and services to close the gaps, with prices."],
  ["Deviation", "A setting found on a device that does not match the target. Critical ones block the certificate."],
  ["Waiver", "An agreed exclusion: work left out by agreement, approved by the Director and acknowledged by the customer."],
  ["Certificate", "The signed record that IITPL implemented the listed work. Its QR code opens a public check page."],
];

function Steps({ steps }: { steps: ReactNode[] }) {
  return (
    <ol className="guide-steps">
      {steps.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ol>
  );
}

export default function Help() {
  const { me } = useMe();
  const mine = new Set<string>(me.roles);
  if (mine.has("sales_head")) mine.add("sales_manager");
  if (mine.has("director")) mine.add("admin"); // the Director does everything an admin does
  const yours = ROLE_SECTIONS.filter((s) => mine.has(s.role));
  const others = ROLE_SECTIONS.filter((s) => !mine.has(s.role));

  return (
    <div className="guide">
      <div className="page-head">
        <div>
          <h1>How to use Project One</h1>
          <p>
            Project One takes a customer from an IT audit to a signed certificate. Each person does their part,
            and someone else approves it.
          </p>
        </div>
      </div>

      {yours.length > 0 && (
        <section className="section">
          <h2>Your part</h2>
          <p className="lede">You are signed in as {me.full_name}. These are the steps for your roles.</p>
          {yours.map((s) => (
            <details key={s.role} open>
              <summary>{s.title}</summary>
              <Steps steps={s.steps} />
            </details>
          ))}
        </section>
      )}

      <section className="section">
        <h2>A project, step by step</h2>
        <ol className="guide-journey">
          {JOURNEY.map((j) => (
            <li key={j.step}>
              <span className="station" aria-hidden="true">
                <j.icon size={18} />
              </span>
              <span>
                <b>{j.step}</b> <span className="muted small">{j.who}</span>
                <span className="guide-what">{j.what}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="muted small">
          A project moves to the next step only when the current one is approved. If a step is sent back, the reason is
          shown at the top of the project.
        </p>
      </section>

      <section className="section">
        <h2>Getting around</h2>
        <ul className="guide-list">
          <li>The sidebar on the left (the menu at the top on a phone) lists only what your role can open.</li>
          <li>
            Inside a project, a task or a catalogue item, <b>&larr; Back</b> at the top returns you to where you were.
          </li>
          <li>A project has tabs, one per step. The step that needs attention is shown at the top of the project.</li>
          <li>A message at the bottom of the screen confirms each action, or says what to fix.</li>
          <li>
            <b>Theme</b> at the bottom of the sidebar switches between light, dark and your device&apos;s setting.
          </li>
        </ul>
      </section>

      <section className="section">
        <h2>First sign-in</h2>
        <Steps
          steps={[
            <>Sign in with your work email and the temporary password your admin gave you.</>,
            <>
              Directors and admins: install Google Authenticator or Microsoft Authenticator, choose <b>Show my code</b>,
              scan the QR code and type the 6 digit code. Save the recovery codes somewhere safe.
            </>,
            <>Afterwards, signing in asks for the code from the app. You then stay signed in on that computer or phone for 14 days, until you sign out.</>,
          ]}
        />
      </section>

      <section className="section">
        <h2>When something goes wrong</h2>
        <dl className="kv">
          <dt>Account locked</dt>
          <dd>Too many wrong passwords. It unlocks by itself after a while, or an admin can unlock it from Accounts.</dd>
          <dt>Lost your phone</dt>
          <dd>Use one of your recovery codes at sign-in, or ask an admin to reset your authenticator.</dd>
          <dt>Forgot your password</dt>
          <dd>Ask an admin for a new temporary one (Accounts, then your name, then Reset password).</dd>
          <dt>&ldquo;Too many requests&rdquo;</dt>
          <dd>Wait a minute and try again.</dd>
          <dt>A button is greyed out</dt>
          <dd>Something before it is not done yet, or another role does that step. The page usually says which.</dd>
        </dl>
      </section>

      {others.length > 0 && (
        <section className="section">
          <h2>Other roles</h2>
          <p className="lede">What your colleagues do, so you know who to ask.</p>
          {others.map((s) => (
            <details key={s.role}>
              <summary>{s.title}</summary>
              <Steps steps={s.steps} />
            </details>
          ))}
        </section>
      )}

      <section className="section">
        <h2>Words used in the app</h2>
        <dl className="kv">
          {GLOSSARY.map(([w, d]) => (
            <div key={w} style={{ display: "contents" }}>
              <dt>{w}</dt>
              <dd>{d}</dd>
            </div>
          ))}
        </dl>
      </section>

      <p className="muted small">
        Still stuck? Ask your project manager, or start from <Link href="/projects">Projects</Link>.
      </p>
    </div>
  );
}
