# ADR 0017: Defaults for BOQ, planning and field work

Status: accepted. Nobody had a firm answer for these yet, so we went with the safest sensible
option. The Director can change any of them; each is a setting or a template, not code.
Decided by: Aditya Kumar
Date: 2026-10-03

## Phase 6 questions

| Question | Default |
| --- | --- |
| Totals and GST rows by default? | Off, matching the samples (ADR 0013). Per quote toggle |
| Quote numbering per company or per salesperson? | One sequence per company per financial year; the issuer's initials appear in the ref (`ITCraft/AK/2627/031`) |
| Who may override prices? | Anyone with BOQ edit rights, with a source note; approval by a Sales head or the Director who did not edit the draft |
| Default recommendation weights? | Need fit 25, budget fit 20, 3-year cost 15, market standing 10, lifecycle 10, vendor preference 10, stock 5, past acceptance 5 (`DEFAULT_WEIGHTS`, seeded in `reco_weights`, editable per segment) |
| Market attributes first? | Rating, analyst tier, India support, end-of-life date |

## Phase 7 questions

| Question | Default |
| --- | --- |
| Engineer calendars and hours | Monday to Saturday, 10:00 to 18:00 IST, leave entered by the project manager |
| Travel time | A fixed 30 minute buffer between tasks at the same site; first task of a day starts at 10:00 |
| Config fields per device type | Seeded config templates for firewall, switch, NAS, server and endpoint (firmware, admin MFA, IPS, VLANs, RAID, encryption, off-site copy, hardening score, patches, memory and others), each with severity and how it is proven |

## Phase 8 questions

| Question | Default |
| --- | --- |
| OTP channel | Email to the customer's sign-off contact. SMS and WhatsApp adapters exist but cost money, so they stay off until a provider is chosen (ADR 0011) |
| Mandatory photo evidence | Site photo at check-in; backup proof and access confirmation at prechecks; per-task evidence from the task template (photos with serials for hardware, config export and screenshot for network devices, before and after screenshots for endpoints) |
| Offline support | 72 hours. Work captured earlier than that is refused and the project manager is told |
| OTP rules | 6 digits, valid 15 minutes, 5 tries, 5 codes an hour, stored as a salted hash, wiped from the message log after an hour |
