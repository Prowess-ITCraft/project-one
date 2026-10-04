# Phase 7: Planning, scheduling and configuration baselines

Window: 2 to 10 Nov 2026 (planned). Status: built (code on 1 Oct, plan PDF on 3 Oct).

## Goal

Turn the accepted BOQ into a plan the team can run: tasks with dependencies, engineers and dates
that respect leave and the customer's downtime windows, and a target configuration for every
device so the work can be checked later.

## Features added

- **Tasks from the BOQ.** Each accepted line becomes one or more tasks from the task library
  (steps, evidence, minutes, device type). Sanitization comes before endpoint security on the
  same machine. Quantities only: plans never carry prices.
- **Scheduler.** Monday to Saturday, 10:00 to 18:00 IST, 30 minute buffer, engineer leave,
  downtime tasks only inside the customer's windows, no double booking.
- **Editing.** Change minutes, engineer, dependencies or notes with a reason; add and delete
  tasks. Any change clears the schedule so it is planned again.
- **Configuration baselines.** One per device, from the config templates (firewall, switch, NAS,
  server, endpoint): each setting has a target, an importance and how it is proven.
- **Locking.** The technical lead or project manager locks the plan; the database refuses
  changes to a locked plan. The gate still needs a second person to approve.
- **Plan document.** `GET /projects/{id}/plan/render` gives the plan as HTML or a WeasyPrint
  PDF: one table per day, downtime windows, target configuration per device.

## Acceptance

| Criterion | State |
| --- | --- |
| Tasks generated from an accepted BOQ | Done, tested |
| Dependencies enforced | Done, tested (and again at check-in in phase 8) |
| Schedule respects downtime windows and leave | Done, tested |
| Each device has a target configuration baseline | Done, tested |
| Plan PDF through the shared renderer | Done, tested (HTML on Windows, PDF in the container) |

## Demo script

1. Accept a BOQ, open the plan, generate, add a downtime window, schedule.
2. Lock the plan as the technical lead.
3. Open the plan document and show the day tables and the firewall baseline.
