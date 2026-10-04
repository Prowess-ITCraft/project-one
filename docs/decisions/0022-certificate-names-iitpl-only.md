# ADR 0022: The certificate names IITPL as the implementer, and only the Director signs

Status: accepted
Date: 2026-10-04
Decided by: Aditya Kumar

## Context

The certificate said the work "was carried out by ITCraft" and carried an "Implemented by
ITCraft" mark next to the QR code, while IITPL issued and signed it. Which company implemented
the work is not fixed per project, and a certificate that names two companies invites a client
to ask which one is answerable. Large projects also listed every task, so a project with 52
tasks ran onto a second page.

## Decision

1. The wording says IITPL implemented all of the listed work, in full and to the agreed target
   configuration, and that every item was checked, verified and accepted by the customer.
2. No "Implemented by" mark. The foot has the QR code, and the Director's signature with the
   IITPL stamp.
3. The work list shows one line per kind of work with a device count ("Upgrade the operating
   system, 8 devices"), at most 10 lines; the completion report keeps the task by task list.
4. Wording can still be changed in certificate settings; it is copied into each certificate's
   signed payload, so certificates already issued keep the words they were issued with.

## Consequences

- One page for any project size; the client reads one company, one signature.
- Exclusions agreed with the client stay on the certificate, so what was left out is on record.
