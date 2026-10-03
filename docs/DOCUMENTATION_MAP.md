# Documentation map

Every document, what it is for, and what must change when a phase ships. The rule: **a phase
is not done until this list has been walked.**

## The six core documents (the project's brain, BUILD_PROMPT section 1)

| Document | Holds | Update when |
| --- | --- | --- |
| `PRD.md` | Purpose, roles, the 8 stages, FRs with phase and state, NFRs, scope | Scope or a requirement changes |
| `ARCHITECTURE.md` | Modules, dependency rules, data model, corpus pipeline, events, ports, security, ADR list | A module, contract, table group or service changes |
| `RULES.md` | Non-negotiables, data rules, hardening, standards, testing, definition of done | A rule changes (owner approval) |
| `DESIGN.md` | UI tokens, type, layout, components, copy, PDF document design | UI or document design changes |
| `TASKS.md` | Phase status, checklists, gaps, next batch | Every task starts, finishes or is blocked |
| `MEMORY.md` | Owner's answers, defaults, environment, stubs, limitations, changelog | End of every session and phase |

## Supporting documents

| Document | Audience | Update when |
| --- | --- | --- |
| `BUILD_PROMPT.md` | Agent and leads | The owner issues a new brief |
| `README.md` (root) | Everyone | Status or entry points change |
| `ROADMAP.md` | Colleagues, managers | Phase status or dates change |
| `phases/phase-NN-*.md` and `phases/README.md` | Colleagues | Each phase |
| `guides/01-beginners-guide.md` | New users | New screens, commands or setup steps |
| `guides/02-developer-guide.md` | Developers | New module, convention, recipe or permission |
| `guides/03-operations-guide.md` | Operators | New setting, service, job, runbook or port |
| `guides/04-api-guide.md` | API users | New endpoints or conventions |
| `guides/05-tech-stack-and-processes.md` | Developers | New technology or process |
| `guides/06-data-guide.md` | Data and ML | Corpus, cleaning, labels or training snapshots change |
| `decisions/NNNN-*.md` | Everyone | Any decision that is not obvious from code |
| `runbooks/` | Operators | Deploy, backup, restore, rollback change |
| `.env.example` | Operators | New setting |

`PROGRESS.md`, `SCOPE.md` and `design/frontend-design-plan.md` are pointers kept for old links.

## Phase checklist

1. Add `phases/phase-NN-*.md`: goal, features, acceptance, decisions, limitations, demo script.
2. Update `TASKS.md`, `MEMORY.md` (changelog), `phases/README.md` and `ROADMAP.md`.
3. Update `PRD.md` FR states and `ARCHITECTURE.md` if modules or tables changed.
4. Update the guides the phase touches. New endpoints always touch the API guide; new screens
   always touch the beginner's guide.
5. ADRs for decisions made without an answer from the owner.
6. Regenerate `frontend/lib/schema.d.ts` if the API changed.
7. Numbers in docs (tests, endpoints, coverage) come from a real run, not memory.
8. Plain writing: no em dashes in docs, UI copy or generated reports.
