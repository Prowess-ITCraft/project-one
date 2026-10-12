# ADR 0031: The IITPL stamp is loaded, never committed or served

Status: accepted
Date: 2026-10-12
Decided by: Aditya Kumar

## Context

IITPL sent the stamp image (647 x 386 PNG, transparent background). It holds the company seal and
the Director's handwritten signature, so anyone who has the file can make a certificate that looks
real. It arrived in `frontend/public/icons/`, where the web app serves every file to anyone without
signing in and the service worker caches `/icons/` on every phone. Certificate settings already
take a stamp upload (Director or Admin), and issuing already needs one (release condition 5).

## Decision

1. The stamp is kept out of git and out of `frontend/public/`. `.gitignore` and the web image's
   `.dockerignore` refuse any `stamp*` file there.
2. It reaches the system only through the existing certificate settings service: the
   Certificate settings page, or `python -m app.cli load-stamp <file or -> --as <email>` on the
   server. The command acts as that named Director or Admin, so the same permission check, type
   check, size limit, virus scan and audit entry apply. It does nothing when that exact file is
   already the stamp (the hash of the file as given is kept with the settings). Production reads
   no file from the frontend.
3. The web app never shows a stamp it does not hold: the settings preview shows the stored stamp,
   or "No stamp yet".
4. Every certificate made outside production (`P1_ENV` is not `prod`) and every sample from
   `render-samples` carries a large "SAMPLE, NOT VALID" mark, so a demo certificate with the real
   stamp never passes for a genuine one. `demo-projects --stamp <file>` and `render-samples
   --stamp <file>` use the real stamp in development; without it the demo keeps its placeholder.
5. On the certificate the stamp sits above the Director's signature line, 26 mm high, clear of
   the name and the QR code.

## Consequences

- A certificate is laid out once, at signing, and its PDF is stored with its SHA-256; downloads
  return those bytes. A later stamp upload cannot change a certificate already issued.
- The signed payload does not name the stamp. If the stamp ever has to be proven from the record
  alone (without the stored PDF), its hash would have to join the payload, which changes the
  signature format; that waits for a decision.
- Whoever loads the stamp needs the file on the server for a moment, or pipes it in with `-`.
