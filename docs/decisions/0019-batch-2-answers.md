# ADR 0019: Batch 2 answers from the owner (phases 9 to 11)

Status: accepted (owner's answers, 3 Oct 2026)
Date: 2026-10-03

| Question | Owner's answer | What it means in the build |
| --- | --- | --- |
| Device brands first | SonicWall first, because it is in the Shakti audit. More brands will come from more sample audits and BOQs | A SonicWall config-export driver first. Drivers stay behind `ConfigCheckDriver` and are registered per brand, so each new brand seen in the library is one new driver, nothing else changes. The library analysis will list brands found in audits that have no driver yet |
| Remote read-only access or evidence | Evidence only, so the work is done to perfection | No device connections in v1. Every check reads uploaded exports, screenshots and recorded values; the evidence rules stay strict |
| Severity rules beyond critical, major, minor | Yes | Rules to be given by the owner (asked on 3 Oct). Until then: critical or major failures send work back; minor failures are listed for the verifier |
| Certificate wording and signer | Director only, with the IITPL stamp | Only the Director can sign. The certificate carries the IITPL stamp image; the owner supplies the stamp file (asked on 3 Oct). The wording is Director-owned text in settings |
| Rescan before the certificate | Yes, with a final check by the Director | An approved PrismSuite rescan is required. The Director reviews before and after scores and signs off; a waiver is possible only by the Director and is printed on the certificate |
| Languages | English only | English only in v1; copy stays in one place per screen |
