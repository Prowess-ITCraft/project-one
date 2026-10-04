# Design

The UI design system and the document (PDF) design system. For a new screen: sketch it here
first, check it against the product read below, change anything that looks like a stock
template, then build.

## 1. Product read

An internal operations tool for Indian IT services staff (sales, architects, engineers,
directors), plus a phone flow for field engineers. Not a marketing page. Calm and minimal, dense
where it helps (BOQ editor, library), very simple on a phone, easy for someone on their first
day. Little variety between screens, no animation, medium density.

Stack limits: Next.js and React only, plain CSS with tokens, Phosphor icons (ADR 0023), no
component libraries, no Tailwind, no chart library (charts are small hand-written SVG).

## 2. Tokens (brand pass, 3 Oct 2026)

Colours come from the companies' own marks (`brand/`): ITCraft's shield blue and circuit green,
IITPL's charcoal. Contrast checked with the WCAG formula.

| Token | Light | Dark | Use | Contrast |
| --- | --- | --- | --- | --- |
| `--paper` | #F3F5F8 | #0D141C | Page background, faintly blue from the brand | |
| `--surface` | #FFFFFF | #142030 | Panels, inputs | |
| `--ink` | #142230 | #E6ECF3 | Text, blue-tinted rather than neutral black | 14.8 / 15.6 |
| `--muted` | #536276 | #97A6B8 | Secondary text | 5.7 / 6.6 |
| `--line` | #DCE2EA | #223244 | Hairlines | |
| `--accent` (ITCraft blue) | #2C629F | #7FB0E8 | Actions, focus, current station | 6.3 / 7.3 |
| `--trace` (circuit green) | #2A9445 | #5DD86B | Completed stations on the rail and the task timeline | 3.9 / 9.0 (graphics) |
| Brand green | #4FCE5D | | Logo only: 2.0 on white is too weak to carry meaning | |

Status colours only for real state: done #1E7A4C, attention #8A5A00, blocked #B42318 (lighter
in dark mode). Radius 6px for controls, 8px for panels, full round only for timeline stations.
No shadows except the focus ring and the drawer. Structure comes from hairlines and spacing.

## 3. Type

Geist for text, Geist Mono for numbers, codes and money (tabular figures). Scale 13, 14, 16,
20, 26. Body 14px on 1.5 line height, lines under 70 characters. Sentence case, no all-caps
labels.

## 4. Layout

```
+-----------+------------------------------------------------+
| Project   |  Shakti Equipments Pvt Ltd / IT hardening      |
| One       |  (o)--(o)--(o)--(o)--(@)--( )--( )--( )         |  stage rail
|           |  ---------------------------------------------- |
| Projects  |  BOQ                         Issue quote        |
| Library   |  table, inline edits, blockers listed above     |
| Catalogue |                                                |
| Users     |                                                |
+-----------+------------------------------------------------+

Phone (field engineer, 360 px):
+------------------------------+
| Today              3 tasks   |
|------------------------------|
| T-04 Managed switch setup    |
| Checked in . step 2 of 5     |   <- one task, one next action
| [ Next: confirm backup ]     |
+------------------------------+
```

Left aligned, one content column up to 1080px. On phones the sidebar becomes a top bar, tables
become stacked rows, the stage rail turns vertical.

## 5. Where boldness goes

Two places only, both drawn in the brand's own idea, a circuit trace:

- **The stage rail**: eight stations on one trace. Approved stations fill with trace green, the
  current one is ringed in ITCraft blue, locked ones are hollow.
- **The task timeline** (field work): the nine states of a task as stations on one trace, the
  current one ringed and labelled with the next action in plain words. When a check fails or a
  verifier sends work back, the trace draws a visible loop back to "configured" with the count,
  so rework is never hidden.

Everything else is quiet: hairlines, type weight, spacing.

## 5a. Screen plans (brand pass)

```
Field engineer, phone (360 px)              Task (phone)
+------------------------------+            +------------------------------+
| [shield] My tasks            |            | < My tasks          Blocked? |
|------------------------------|            | T-03 Firewall setup          |
| Today, 12 Nov                |            | Shakti Equipments, FW-01     |
| T-03 Firewall setup          |            | o--o--@--o--o--o--o--o--o    |  timeline
|   Checked in                 |            |                              |
|   Next: add the backup       |            | Next: add the backup         |
| T-04 Switch install    10:30 |            | [ Take photo ]   (big)       |
|   Waiting for T-03           |            | ---------------------------- |
| Tomorrow                     |            | Steps 2 of 5, values, files  |
| ...                          |            | 2 actions waiting to send    |
+------------------------------+            +------------------------------+
```

- **Library** (desktop): drop zone, then three tabs: Files (with held rows to confirm), Corpus
  (one row per converted document: size before and after, quality, labels), Data quality
  (corpus totals, label balance, price bands per gap type, flagged outliers).
- **Review queue** (technical lead): a list of handed-over tasks, oldest first; a task opens with
  its checks, values and evidence beside the approve and send-back actions.
- **Project, Plan and Field work tabs**: plan generation, downtime, schedule, lock and the plan
  document; field work start, a count per state on the trace, blocked and late lists, a live feed.

## 5c. Sign-in and shell (basic, pleasant, not heavy)

Sign-in palette: shield navy #0F2A45 (the logo blue, deepened), raised navy #163657 for the
step icons, panel text #EEF3F9 (13.4:1), panel secondary #B9CBDD (8.6:1), circuit green #4FCE5D
on navy (7.2:1, so here the logo green can carry meaning). The form sits on a white panel over
`--paper`.

```
+-----------------------------+---------------------------------------+
| [shield] Project One        |  navy                                 |
|          ITCraft            |  From the audit report to a           |
| +-------------------------+ |  signed certificate.                  |
| | (shield icon)           | |   (doc) Audit intake                  |
| | Sign in                 | |     |   Audit engineer                |
| | ITCraft or IITPL email  | |   (pc)  Current IT                    |
| | [@ name@itcraft.net.in] | |     |   Solution architect ...        |
| | [lock ..........  eye ] | |   (wrench) Field work                 |
| | [ ->] Sign in         ] | |   (cert) Certified by IITPL [IITPL]   |
| | (?) Forgot password...  | |                                       |
| +-------------------------+ |                                       |
| (wrench) Development login  |                                       |
+-----------------------------+---------------------------------------+
Phone: a slim navy band, the brand, then the form; the journey is for big screens.
```

- The one memorable element: the project's steps on one trace, each with its icon and who does
  it, ending on the IITPL certificate mark. Still, nothing moves.
- Form care: autofocus, an icon in each input, show or hide password as an eye icon, Caps Lock
  warning, full-width 46 px button, errors under the field, a recovery code option when the
  phone is lost, the authenticator set-up shows a scannable QR code.
- Shell: sidebar on a second neutral layer (#EAEFF5), an icon beside every item, the current
  page as a raised white chip with a filled icon, the signed-in person as an initials badge,
  44 px tap targets on phones, primary buttons with a soft tinted shadow.
- Getting around: inner pages (a project, a task, a catalogue item, an import) start with
  "Back" plus the section they belong to; Help is in every sidebar, and a one-line hint points
  new people to it until they open it or hide it.
- Navy with a bright green can look like every other dark landing page. We kept it because both
  colours come from the ITCraft logo and the green only marks progress; every action stays
  ITCraft blue and the form side stays light.

## 5b. Design review notes

- The first accent, cobalt #2A4FD6, looked like any SaaS product. Switched to ITCraft's own blue.
- Field progress started as a row of big number tiles. It said little, so the counts now sit on
  the same trace as the task timeline.
- Icons were first left out entirely. Screens read as walls of words and new people had to read
  every label, so Phosphor icons were added beside the words (ADR 0023).
- The sign-in trace used to light up on load. Mid-animation it looked faint and unfinished; the
  panel is now drawn complete and still.
- Engineers work in sunlight: the field screens use the ink colour at full strength, 16 px body
  and 48 px primary buttons.

## 6. Components and copy

- Buttons named by what people do: "Issue quote", "Send code to customer", "Mark backup done".
- One primary action per view. Destructive actions ask for a reason, not a confirm dialog.
- Errors say what happened and how to fix it. Empty states offer the next action.
- Badges are text, not dots. No arrows on buttons, no fade-in on every section, no eyebrow
  labels, no identical rounded cards, no middle-dot meta strings.

## 7. Quality floor

Responsive to 360px, keyboard reachable with visible focus, WCAG AA contrast in both themes,
no animation, light and dark themes following the system with a manual switch.

## 8. Document design (PDF)

All documents are HTML and print CSS rendered by WeasyPrint (`core/documents.py`).

- A4, margins 16 / 14 / 18 / 14 mm, page number "Page N of M" in the footer, table rows never
  split across pages (`page-break-inside: avoid`), table header repeated on each page.
- Font: DejaVu Sans, loaded with `@font-face` from the image (renders the rupee sign and Indian
  grouping). Numbers right aligned. 9pt body, 13pt title.
- Letterhead, address, phones, email, GSTIN, terms, signatory: from company settings, never in
  the template.
- **Quotation** (exact ITCraft format): letterhead, QUOTATION, "To," block with date and quote
  ref, table `Sr N | Components | Qty | Price | Amount`, grey group rows (High Priority, To
  Consider), italic section rows, bold line titles with bullet inclusions, options 6A and 6B
  never summed, terms, signature. Totals rows only when the quote turns them on.
- **Summary BOQ**: the same, without Price and Amount.
- **Plan and schedule**: project header, one table per day (time, task, engineer, asset,
  downtime flag), dependency notes, configuration baselines per device.
- **Checklist export**: one task per page, timeline of states with time and place, steps with
  times, evidence list with thumbnails, OTP confirmations (masked contact), verifier decision.
- **Completion report**: scope delivered, exclusions (waivers), before and after scores on the
  four lenses, configuration per device, deviations, open recommendations. No prices.
- **Certificate**: one landscape page, IITPL mark and stamp, Director's signature, certificate
  number and a QR code to the public check page.
