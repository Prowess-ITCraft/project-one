# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Office staff on desktop** (confirmed): sales and BD managers, the sales head, solution
  architects, audit engineers, project managers, technical leads (verifiers) and the Director at
  ITCraft / IITPL. They import audits, review gaps, build and issue quotations, plan work,
  verify field work and approve stage gates. Long sessions, dense tables, keyboard use.
- **Field engineers on Android phones** (confirmed): on customer sites, often with weak signal,
  one hand busy with equipment. They accept tasks, check in with a customer code, take photos,
  tick steps, record what they see on devices and hand over with a second code.
- **Customer representatives**: receive codes and updates by email; no portal in v1.

## Product Purpose

Project One turns a PrismSuite IT audit into a verified, certified implementation: audit intake,
current and ideal infrastructure, gap register, BOQ and quotation in the exact ITCraft format,
implementation plan, gated field work, verification, and a "Certified by IITPL" certificate.
Success: a quotation drafted from an approved audit in minutes, field work that cannot skip a
step, and a certificate that is only possible when every condition is met.

## Positioning

The only tool that carries one customer engagement from the audit report to a signed
certificate with approval gates between every stage, the person who did the work never
approving it, and customer one-time codes proving the engineer was there.

## Operating Context

- Eight stages, each closed by a named approval gate; outputs are locked versions.
- Quotations follow the ITCraft letterhead format (rupees with Indian grouping, options 6A and 6B
  never added together, GST 18% extra).
- Old BOQs and PrismSuite reports keep arriving and become the training library.
- Field engineers work offline for up to 72 hours; their actions sync later.

## Capabilities and Constraints

- Stack is fixed: Next.js and React only, plain CSS, no component, icon or chart libraries.
- Field engineers never see prices anywhere.
- Every screen works at 360 px, by keyboard, in light and dark themes, with reduced motion.
- Language: English only in v1 (inferred default, the owner did not choose; keep copy in one
  place so Hindi or Marathi can be added later).

## Brand Commitments

- Two companies: **ITCraft** (Prowess IT Craft Pvt Ltd) issues quotations and runs the work;
  **IITPL** (International Infocom Technologies Pvt Ltd) certifies it.
- Logos from the companies' websites are in `brand/`: `itcraft-logo.svg` (shield mark, blue
  #2C629F and green #4FCE5D), `itcraft-icon.png`, `iitpl-logo.png` (tree of circuit lines,
  charcoal #464749, red #E50019, green #4D9261), `iitpl-icon-192.png`.
- Writing: plain English, sentence case, no em dashes.

## Evidence on Hand

- `samples/`: one PrismSuite audit (Shakti Equipments) and two ITCraft BOQs (Shobhaglobs), plus
  their canonical JSON in `samples/corpus/`.
- No testimonials, customer counts or case studies exist; do not invent any.

## Product Principles

1. One next action: every screen says what to do next and what blocks it.
2. Nothing silent: missing prices, unread fields and failed checks are shown, never guessed.
3. The doer never approves their own work.
4. Data is an asset: every file is kept, cleaned and explained.
5. Calm by default, dense where the work is dense.

## Accessibility & Inclusion

WCAG 2.2 AA in both themes, visible focus, 44 px touch targets in the field flow, reduced motion,
readable in sunlight on a phone (high contrast in the field screens).
