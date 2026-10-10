# ADR 0027: The field app on phones: location at check-in, 72 hours offline

Status: accepted
Date: 2026-10-08
Decided by: Aditya Kumar

## Context

Field engineers work from their own phones, Android and iPhone, at customer sites where the
signal is often weak. The field pages had to become an app they can install, that keeps working
without signal, and that records where and when evidence was taken. Three choices were open:
which phones to support, whether the phone's location is required, and how long work may stay
on the phone before it is sent.

## Decision

1. **Both Android and iPhone.** The field pages are an installable web app (manifest, service
   worker, install prompt, a "New version ready, reload" banner). Browser tests run on an
   Android and an iPhone screen size. On iPhone, Web Push works only after Add to Home Screen,
   and the Messages settings say so.
2. **Location is required at check-in, best effort elsewhere.** Check-in is refused without the
   phone's location (`location_required`), and the arrival photo must carry it. On every other
   step, a denied or missing location is recorded as "location not available" with the reason,
   and the step goes on.
3. **Work may stay on the phone for up to 72 hours.** Everything between check-in and sending
   the task for checking can be done offline. Each item carries an idempotency key and the time
   it really happened; the server keeps its own receipt time and a hash, and those are the
   record. Work older than 72 hours is refused with a reason the engineer can see. Check-in and
   hand over need signal while customer codes are on (ADR 0025).
4. **Sync without depending on the browser.** The outbox sends on app open, on reconnect, every
   30 seconds while there is work waiting, on Sync now, and through Background Sync where the
   phone supports it (not iPhone). Server state wins on a conflict and the phone shows what was
   refused and why.
5. **A lost or shared phone.** The field app signs out after 15 minutes idle, warns at sign-out
   when work is still waiting, and clears its caches on sign-out. It never caches prices or
   another role's data; a backend test fails if any route sends a price field to a field
   engineer.
6. **Evidence stamps.** Photos get the time, location and task number drawn onto a copy; the
   original is kept as well.

## Consequences

- An engineer with location switched off cannot check in. The message says how to turn it on.
- A phone left offline for more than three days loses the waiting work after it is refused, so
  the Director's dashboard shows each engineer's phone state ("offline, last sync 14:02").
- iPhone users must install the app to get push messages; email still reaches them.
