# Project One roadmap: October to December 2026

How the 15 phases are paced through to a 31 December go-live. Dates are planning targets,
not commitments. Status is the real state of the code on 4 October 2026; several phases landed
well ahead of their window.

Project One turns a PrismSuite IT audit into a verified, certified implementation for
ITCraft / IITPL: audit intake, gap analysis, BOQ and quotation, implementation plan, gated
field work, verification, and a "Certified by IITPL" certificate.

## At a glance

| Milestone | Phases | Window | Theme | Status |
| --- | --- | --- | --- | --- |
| M1 | 1, 2, 3 | 28 Sep to 9 Oct | Foundation, people and access, audit intake and price book | Built |
| M2 | 4, 5, 6 | 12 Oct to 6 Nov | Datasets, infrastructure gaps, BOQ and recommendations | Built |
| M3 | 7, 8, 9 | 2 Nov to 24 Nov | Planning, field operations, verification, Director dashboard | Built |
| M4 | 10, 11, 12 | 23 Nov to 16 Dec | Completion certificate, then the whole web app | 10 and 11 built, 12 nearly done |
| M5 | 13, 14, 15 | 14 Dec to 31 Dec | Learning from the library, hardening, go-live | 13 built (waiting for data); 14 next |

## Timeline

```
Sep           Oct                     Nov                     Dec
28  5  12  19  26  2   9  16  23  30  7  14  21  28
P1  ###
P2   ####
P3      ####
P4          #####
P5              #####
P6                  #######
P7                      #####
P8                          ######
P9                              #####
P10                                 #####
P11                                     ######
P12                                          ######
P13                                               #####
P14                                                #######
P15                                                     #######
```

## Phase by phase

| # | Phase | Target dates | What colleagues will be able to see |
| --- | --- | --- | --- |
| 1 | Platform foundation | 28 Sep to 2 Oct | The whole system starts with one command. Health, metrics, logs, backups. |
| 2 | Identity, access, audit log, customers and projects | 1 to 6 Oct | Sign in with MFA, roles, customers and projects moving through eight approval gates. |
| 3 | PrismSuite intake, catalogue, price book | 5 to 9 Oct | Upload the Shakti audit report, see every score and count extracted, correct and approve it. Price book with expiry. |
| 4 | Dataset engine | 12 to 20 Oct | Import old BOQs, clean them, explore and chart them, export. |
| 5 | Infrastructure model, rule library, gap engine | 19 to 27 Oct | Current vs ideal infrastructure and a prioritised gap register from an approved audit. |
| 6 | BOQ and recommendation engine | 26 Oct to 6 Nov | A BOQ drafted from the gaps in minutes, rendered as the exact ITCraft quotation PDF and Excel. |
| 7 | Planning and configuration baselines | 2 to 10 Nov | Tasks, dependencies, engineer schedule. |
| 8 | Field operations | 9 to 18 Nov | The "food delivery" task flow: no step is skipped, customer OTP at check-in and handover. |
| 9 | Verification and Director dashboard API | 16 to 24 Nov | Actual vs target configuration checks and live project status for the Director. |
| 10 | Completion report and certificate | 23 Nov to 1 Dec | Certificate with QR verification, blocked unless every condition is met. |
| 11 | Frontend foundation | 30 Nov to 9 Dec (first slice done 1 Oct) | Design system, sign in, app shell, projects, audit review, catalogue are built. Gap register follows phase 5. |
| 12 | Frontend core workflows | 7 to 16 Dec | BOQ editor, dataset workspace, planner, engineer mobile flow, Director live view. Each screen lands when its backend phase does. |
| 13 | ML pipeline | 14 to 21 Dec | Learned BOQ and ranking models running in shadow next to the rules. |
| 14 | Hardening and performance | 15 to 24 Dec | Load tests, security review, backup and restore drill. |
| 15 | Go-live | 21 to 31 Dec | Production deployment, runbooks, training, rollback plan. |

## Milestones and demos

| Date | Milestone | Demo |
| --- | --- | --- |
| 9 Oct | M1 | Upload the sample audit, review, approve; open the price book; show the audit trail. |
| 6 Nov | M2 | Approved audit to gap register to BOQ to quotation PDF identical in layout to ITCraft's. |
| 24 Nov | M3 | A task walks from assigned to closed with OTP, evidence and verification. |
| 16 Dec | M4 | Full web app, certificate issued and verified by QR. |
| 31 Dec | M5: Go-live | Production running, backups proven, team trained. |

## Risks to watch

- Sample data is thin: one PrismSuite report and two BOQs. Parser and ML quality depend on
  more samples (Phase 13 needs many manual BOQs).
- Questions about money, certification and security rules need an answer before the phase
  that uses them; the plan assumes quick answers. Open now: severity rules, the IITPL stamp.
- Year-end holidays leave about a week of slack in M5. Phase 15 is the flexible one.

## Where to read more

- What each finished phase delivered: [docs/phases](phases/README.md)
- Every document and when to update it: [DOCUMENTATION_MAP.md](DOCUMENTATION_MAP.md)
- Why decisions were made: [docs/decisions](decisions)
- Where the work stands: [TASKS.md](TASKS.md)
