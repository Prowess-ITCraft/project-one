# Memory

What a new session must know. Read first, then `TASKS.md`.

## Owner's standing answers

- "Assume the best answers possible": choose safe defaults, record ADRs, flag them in the batch
  report. Never guess money, certification or security rules silently.
- Free and open-source only (ADR 0011). Valkey instead of Redis.
- Old BOQs and PrismSuite reports will keep arriving. Every file is converted once to compact
  JSON and kept as training data (ADR 0014). Treat sample and library data as a product asset.
- Frontend: Next.js and React only, plain CSS, minimal and very user friendly.
- No em dashes in docs, UI copy or generated documents.
- Commit only when the owner asks. The repo has no commits yet.

## Defaults chosen (ADRs)

| Topic | Default | ADR |
| --- | --- | --- |
| Totals and GST rows | Off by default, per quote toggle | 0013 |
| Quote refs | One sequence per FY, issuer initials in the ref | 0013, 0017 |
| Pricing approval | Sales head or Director who did not edit | 0013 |
| Engineer hours | Mon to Sat, 10:00 to 18:00 IST, 30 min buffer | 0017 |
| OTP channel | Email to the sign-off contact (SMS, WhatsApp adapters off) | 0017 |
| Offline window | 72 hours | 0017 |
| Field states | v2.1 brief; dependents may start after hand over | 0015 |
| Originals retention | Keep forever (0 days) | 0014 |
| PDF | WeasyPrint only, through `core/documents.py` | 0016 |

## Environment facts

- Windows 11, Docker Desktop (start it by hand), Python 3.12 in `backend/.venv`, Node 22.
- Use `backend/.venv/Scripts/python.exe`. `make` is not installed; use `scripts/dev.ps1`.
- WeasyPrint cannot load on Windows; PDFs answer 503 `pdf_unavailable` outside the container.
- The full test suite takes about 8 to 10 minutes (testcontainers start Postgres, Valkey, MinIO).
- Bash heredocs with quotes or backslashes get mangled by the tool runner; write scripts to the
  scratchpad with the Write tool and run them. The Write tool turns `\u` escapes in content into
  literal characters; use a script for Unicode escapes.
- Another local project (`salt-and-story`) may hold Docker containers; ports 9595 to 9606 are ours.
- Git Bash rewrites `/data/...` arguments into Windows paths; prefix docker exec commands with
  `MSYS_NO_PATHCONV=1`.
- The Claude Chrome extension may be disconnected; headless Chrome with `--remote-debugging-port`
  and the venv's `websockets` package can sign in and screenshot instead.

## Stubs and interfaces

| Interface | v1 | Filled by |
| --- | --- | --- |
| `fieldops.engine.ConfigCheckDriver` | `AnswerDriver` judges recorded values; free-text targets go to the verifier | Phase 9 brand drivers via `register_driver` |
| `notifications.providers` SMS, WhatsApp | `UnconfiguredProvider` (recorded as skipped) | When a provider is chosen |
| `boq.recommend` learned ranker | Rule-based only | Phase 13 (shadow mode) |
| Market data feed | Manual entry | Later, behind the feed adapter |

## Known limitations

- The answer driver cannot judge free-text targets such as "Managed, reachable on the
  management VLAN"; those are `not_checked` and the verifier decides.
- Issued BOQ PDFs are rendered on request, not stored in MinIO yet (TASKS.md).
- The cleaning taxonomy is keyword rules (CLEANING_VERSION 1). More real BOQs will show gaps;
  unlabelled lines are listed in the analysis as `other`.
- Only one PrismSuite sample and two BOQ samples exist. Parser and label quality need more.

## Answers for Batch 2 (owner, 3 Oct 2026, ADR 0019)

1. Brands: SonicWall first; more brands as more sample audits and BOQs arrive (one driver each).
2. Evidence only, no remote device access, so the work is done to perfection.
3. Severity rules beyond critical, major and minor: yes. **Still needed: the rules themselves.**
4. Certificate: signed by the Director only, with the IITPL stamp. **Still needed: the stamp image.**
5. PrismSuite rescan required before the certificate, with a final check by the Director.
6. English only.

## Changelog

- 2026-10-03 (night): Owner answered the Batch 2 questions (ADR 0019); still needed: severity
  rules and the IITPL stamp image. `cli render-samples` renders all four PDFs from the samples;
  PDF defects found and fixed; cleaning v2. Backend: 302 tests at 86 percent before these fixes;
  the affected modules (115 tests) pass after them.

- 2026-10-03 (evening): Sign-in redesigned (navy circuit panel, show password, Caps Lock,
  QR code for authenticator set-up, development login box on localhost) and a light shell
  polish. Owner asked: demo login `adi@test.com` / `test1234` is now **Admin** plus every role
  except Director, so its first sign-in sets up an authenticator (MFA kept, not bypassed).
  Outbox start-up guard (ADR 0018). Screens checked with headless Chrome over CDP
  (scratchpad `shots.py`), using a temporary viewer account that was deactivated afterwards.

- 2026-10-03 (later): Brand pass with ITCraft and IITPL logos (`brand/`). Owner: office on desktop,
  engineers on phones; brand from itcraft.net.in and iitpl.co.in; language not chosen, English only assumed
  (PRODUCT.md). Impeccable installed in `.claude/` with its design hook on (installer needed
  `IMPECCABLE_BUNDLE_PATH` because it follows only one redirect). Field, review, plan and library screens built.

- 2026-10-03: v2.1 brief installed. Six core docs created. Reconciliation run (222 tests).
  Document corpus and cleaning (ADR 0014). Shared PDF renderer (0016). Plan PDF. Field ops
  rebuilt to the v2.1 state machine (0015) with engine check, verifier queue, notifications,
  live feed and checklist PDF. Inbox and notification jobs scheduled. Defaults in 0017.
- 2026-10-01: Phases 4 to 6, planning code, first web app slice (see `PROGRESS.md` history).
- 2026-09-30: Phases 1 to 3.
