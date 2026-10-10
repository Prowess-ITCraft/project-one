# Documentation map

Every document, who it is for, and when it needs touching. A phase is not done until this list
has been walked.

## Core documents

| Document | Holds | Update when |
| --- | --- | --- |
| `PRD.md` | Purpose, roles, the 8 stages, requirements with phase and state, scope | Scope or a requirement changes |
| `ARCHITECTURE.md` | Modules, dependency rules, data model, corpus pipeline, events, ports, security, ADR list | A module, contract, table group or service changes |
| `RULES.md` | Non-negotiables, data rules, hardening, standards, testing, definition of done | A rule changes (needs sign-off) |
| `DESIGN.md` | UI tokens, type, layout, components, copy, PDF document design | UI or document design changes |
| `TASKS.md` | Phase status, open items, open questions | A task starts, finishes or is blocked |
| `NOTES.md` | Ground rules, defaults, machine quirks, stubs, limitations, changelog | A default, stub or limitation changes; each phase |

## Supporting documents

| Document | Audience | Update when |
| --- | --- | --- |
| `README.md` (root) | Everyone | Status or entry points change |
| `ROADMAP.md` | Colleagues, managers | Phase status or dates change |
| `phases/phase-NN-*.md` and `phases/README.md` | Colleagues | Each phase |
| `guides/01-beginners-guide.md` | New users | New screens, commands or setup steps |
| `guides/02-developer-guide.md` | Developers | New module, convention, recipe or permission |
| `guides/03-operations-guide.md` | Operators | New setting, service, job, runbook or port |
| `guides/04-api-guide.md` | API users | New endpoints or conventions |
| `guides/05-tech-stack-and-processes.md` | Developers | New technology or process |
| `guides/docker.md` | Developers, operators | A Docker file, service, profile or command changes |
| `guides/06-data-guide.md` | Data and ML | Corpus, cleaning, labels or training snapshots change |
| `decisions/NNNN-*.md` | Everyone | Any decision that is not obvious from code |
| `runbooks/` | Operators | Deploy, backup, restore, rollback change; `incident.md` when something breaks; `alerts.md` what each alert means and what to do; `security-review.md` the ASVS Level 2 review |
| `.env.example` | Operators | New setting |

## Phase checklist

1. Add `phases/phase-NN-*.md`: goal, features, acceptance, decisions, limitations, demo script.
2. Update `TASKS.md`, the `NOTES.md` changelog, `phases/README.md` and `ROADMAP.md`.
3. Update `PRD.md` requirement states and `ARCHITECTURE.md` if modules or tables changed.
4. Update the guides the phase touches. New endpoints always touch the API guide; new screens
   always touch the beginner's guide.
5. An ADR for every decision made without a firm answer.
6. Regenerate `frontend/lib/schema.d.ts` if the API changed.
7. Numbers in docs (tests, endpoints, coverage) come from a real run.
8. No em dashes in docs, UI copy or generated reports.
