# Project One — logic maps

This is a Mermaid-first map of the implemented platform logic. It is derived from
`README.md`, `PRODUCT.md`, `docs/ARCHITECTURE.md`, phase documents, ADRs, API routes,
and the backend module/state-machine code. It is deliberately local-only: see `.gitignore`.

## 1. End-to-end engagement

```mermaid
flowchart LR
  A[PrismSuite audit] --> B[Audit intake]
  B --> C[Current infrastructure]
  C --> D[Ideal infrastructure]
  D --> E[Gap analysis]
  E --> F[BOQ and quotation]
  F --> G[Implementation plan]
  G --> H[Field work and verification]
  H --> I[Completion report]
  I --> J[Certified by IITPL]

  L[Old audits and BOQs] --> K[Library and corpus]
  K --> E
  K --> F
  F --> M[Accepted BOQ outcomes]
  M --> N[Shadow learning only]
  N -. never changes a decision .-> F
```

## 2. System shape and trust boundaries

```mermaid
flowchart TB
  subgraph people[People and clients]
    Office[Office browser]
    Phone[Field engineer phone]
    Customer[Customer email / public QR check]
  end
  subgraph edge[Public edge]
    Nginx[Nginx: only public production endpoint]
    Web[Next.js web app]
    API[FastAPI modular monolith]
  end
  subgraph services[Private services]
    Postgres[(PostgreSQL)]
    Valkey[(Valkey)]
    MinIO[(MinIO object storage)]
    Celery[Celery worker and beat]
    ClamAV[ClamAV]
    Mail[Email / Web Push providers]
  end
  subgraph ops[Admin-only profiles]
    Metrics[Prometheus + Grafana]
    Errors[GlitchTip]
    MLflow[MLflow optional]
  end

  Office --> Nginx
  Phone --> Nginx
  Customer --> Nginx
  Nginx --> Web
  Nginx --> API
  API --> Postgres
  API --> Valkey
  API --> MinIO
  API --> ClamAV
  API --> Celery
  Celery --> Postgres
  Celery --> MinIO
  Celery --> Mail
  API --> Metrics
  API --> Errors
  Celery --> MLflow
```

## 3. Backend modules and permitted dependencies

```mermaid
flowchart LR
  Core[core: configuration, DB, crypto, outbox, files, idempotency]
  Identity[identity + audit log]
  Customers[customers: projects and gates]
  Ingest[files + PrismSuite + datasets]
  Design[infra + catalogue]
  Delivery[BOQ + planning + fieldops]
  Assurance[verification + reporting]
  Support[notifications + search]
  Learning[ml]

  Core --> Identity
  Core --> Customers
  Core --> Ingest
  Core --> Design
  Core --> Delivery
  Core --> Assurance
  Core --> Support
  Core --> Learning
  Customers --> Delivery
  Ingest --> Design
  Ingest --> Delivery
  Design --> Delivery
  Delivery --> Assurance
  Delivery --> Learning
  Delivery -. domain events .-> Support
  Ingest -. domain events .-> Support
  Design -. domain events .-> Support
  Assurance -. domain events .-> Support
  Learning -. shadow outputs only .-> Delivery
  Assurance -. no imports allowed .-> Learning

  classDef rule fill:#fff1f1,stroke:#b42318,color:#611a15;
  class Learning rule;
```

Rules: modules import another module only through `contracts.py` or react to an outbox event;
`core` imports no module; verification and reporting cannot import ML.

## 4. Protected request and write path

```mermaid
flowchart TD
  R[Request] --> N[Nginx request ID, sign-in rate limit, metrics hidden]
  N --> M[FastAPI body limit, security headers, structured request log]
  M --> T{Valid active session?}
  T -- no --> E401[401 problem response]
  T -- yes --> C{Changing cookie request has CSRF header?}
  C -- no --> E403[403 problem response]
  C -- yes --> P{Permission granted?}
  P -- no --> E403
  P -- yes --> O{Object / project access?}
  O -- no --> E403
  O -- yes --> S[Service applies business rule]
  S --> X{Valid state, version and separation of duties?}
  X -- no --> E409[409 problem response]
  X -- yes --> W[One transaction: domain change + audit entry + outbox event]
  W --> Commit[Commit]
  Commit --> OK[Typed response]
```

## 5. Eight-stage gate protocol

```mermaid
flowchart LR
  A[1 Audit intake\nlocked PrismSuite audit] --> B[2 Current IT\nlocked current model]
  B --> C[3 Ideal IT\nlocked ideal model]
  C --> D[4 Gaps\nlocked gap register\ncustomer acknowledgement]
  D --> E[5 BOQ\nlocked BOQ version]
  E --> F[6 Implementation plan\nlocked plan]
  F --> G[7 Field work\nlocked field summary]
  G --> H[8 Completion\nlocked report\ncustomer acknowledgement]
  H --> Z[Director issues certificate]

  Q[For every stage:\nowner locks artifact] --> Submit[Submit stage]
  Submit --> Ack{Customer acknowledgement required?}
  Ack -- yes --> CustomerAck[Single-use acknowledgement]
  Ack -- no --> Approve
  CustomerAck --> Approve{Configured approver is not\nartifact locker or submitter?}
  Approve -- no --> Reject[Refuse / return for correction]
  Approve -- yes --> Decision[Record permanent gate decision]
  Decision --> Next[Advance to next stage]
```

## 6. Audit import and document corpus

```mermaid
flowchart TD
  Source[Upload, watched inbox, or samples] --> Sniff[Byte sniff + purpose size cap]
  Sniff --> Scan{ClamAV clean?}
  Scan -- no / unavailable --> Reject[Reject upload]
  Scan -- yes --> Store[Random key in versioned MinIO bucket\nSHA-256 + audit entry]
  Store --> Extract[Extract pages and tables\nPDF, DOCX, XLSX]
  Extract --> Parse[Versioned parser\nAuditSnapshot or BOQ document]
  Parse --> Review{Required fields or conflicts?}
  Review -- yes --> Correct[Reviewer adds correction with reason]
  Correct --> Review
  Review -- no --> Approve{Different reviewer approves?}
  Approve -- no --> Pending[Remain unapproved]
  Approve -- yes --> Locked[Locked audit artifact + event]

  Parse --> Clean[Normalise, label, deduplicate, parse money/dates]
  Clean --> Quality[Score completeness, validity, consistency, uniqueness, outliers]
  Quality --> Corpus[Canonical p1.corpus.v1 JSON + corpus row]
  Quality --> Rows[Versioned Parquet collection rows]
  Quality --> Quarantine[Low-confidence quarantine]
  Corpus --> Analysis[Statistics, price bands, quantities, option pairs, drift]
```

## 7. Infrastructure, gaps, BOQ, and quote controls

```mermaid
flowchart TD
  Audit[Approved audit / project brief] --> Current[Current infrastructure model]
  Current --> Ideal[Ideal model from rule library]
  Ideal --> Gaps[Compare current vs ideal\ncreate gap register]
  Gaps --> GapGate{Gap gate acknowledged and approved?}
  GapGate -- no --> Block[Official BOQ blocked]
  GapGate -- yes --> Recommend[Templates + quantity rules + catalogue + history\nrank recommendations]
  Recommend --> Draft[Editable BOQ draft]
  PriceBook[Append-only price book\nactive and not expired] --> Draft
  Draft --> PriceCheck{All prices present and pricing valid?}
  PriceCheck -- no --> Missing[Leave price blank / surface missing prices]
  PriceCheck -- yes --> Margin{Any line below minimum margin?}
  Margin -- yes --> LineAck[Sales Head or Director\naccepts each line with reason]
  Margin -- no --> Lock
  LineAck --> Lock[Lock BOQ version + render ITCraft PDF]
  Lock --> BOQGate[BOQ gate approval by Sales Head or Director\nnot the drafter/editor]
  BOQGate --> Outcome{Customer outcome recorded?}
  Outcome -- accepted --> Examples[Keep recommendation candidates\nand outcome labels]
  Outcome -- not accepted / pending --> FollowUp[Quote follow-up]
```

An early **estimate** may be drafted from a report before approvals; it is visibly “estimate,
not approved” and does not replace the official, gap-register-based BOQ.

## 8. Planning and field task state machine

```mermaid
stateDiagram-v2
    [*] --> assigned
    assigned --> accepted: Engineer accepts
    accepted --> checked_in: Dependencies done, arrival evidence and location confirmed
    checked_in --> prechecks_done: Backup and access confirmed
    prechecks_done --> configured: Ordered steps done, all baseline values recorded
    configured --> evidence_uploaded: All required evidence supplied
    evidence_uploaded --> engine_check: Run automatic baseline comparison

    engine_check --> configured: Critical or major failure, or missing work
    engine_check --> verifier_review: Checks pass and handover confirmed
    verifier_review --> configured: Independent verifier rejects with reason
    verifier_review --> closed: Independent verifier approves

    assigned --> blocked
    accepted --> blocked
    checked_in --> blocked
    prechecks_done --> blocked
    configured --> blocked
    evidence_uploaded --> blocked
    engine_check --> blocked
    verifier_review --> blocked

    blocked --> accepted: Manager unblocks before on-site start
    blocked --> checked_in: Manager unblocks after check-in
    blocked --> prechecks_done: Manager unblocks
    blocked --> configured: Manager unblocks
    blocked --> evidence_uploaded: Manager unblocks
    blocked --> engine_check: Manager unblocks
    blocked --> verifier_review: Manager unblocks

    note right of checked_in
        Customer code required only
        when the feature flag is enabled
    end note

    note right of verifier_review
        Handover customer code required
        only when the feature flag is enabled
    end note

    closed --> [*]
```

Each field action carries a client event ID and capture time for idempotent, offline sync up to
72 hours. The doer may never verify their own task; the phone receives neither prices nor other
roles’ answers.

## 9. Configuration check and deviations

```mermaid
flowchart TD
  Baseline[Plan configuration baseline] --> Check[ConfigCheckDriver]
  Answers[Engineer-recorded values] --> Check
  Exports[Uploaded config exports] --> Reader[Brand export reader\nSonicWall: exp, text, JSON]
  Reader --> Maps[Confirmed / unconfirmed field mappings]
  Maps --> Check
  Check --> Result{Per field: pass, fail, or not checked}
  Result --> Critical{Critical or major failure?}
  Critical -- yes --> Rework[Task returns to configured\nopen/update deviation]
  Critical -- no --> Review[Verifier review]
  Result --> Minor[Minor failure\nopen deviation, does not automatically return task]
  Result --> Unknown[Not checked\nverifier judges manually]
  Minor --> Review
  Unknown --> Review
  Review --> Resolve[Later pass resolves deviation]
  Review --> Accept{Verifier can accept under severity policy?}
  Accept -- yes, with reason --> Accepted[Accepted deviation]
  Accept -- no --> Rework
```

## 10. Completion report and certificate release logic

```mermaid
flowchart TD
  Start[Director requests certificate] --> T1{Every task closed\nor customer-acknowledged waiver?}
  T1 -- no --> Stop[Show unmet conditions; cannot issue]
  T1 -- yes --> T2{No open certificate-blocking deviation?}
  T2 -- no --> Stop
  T2 -- yes --> T3{No waiver awaiting Director or customer?}
  T3 -- no --> Stop
  T3 -- yes --> T4{After-work PrismSuite rescan approved?}
  T4 -- no --> Stop
  T4 -- yes --> T5{IITPL stamp uploaded?}
  T5 -- no --> Stop
  T5 -- yes --> T6{Completion report locked with SHA-256?}
  T6 -- no --> Stop
  T6 -- yes --> T7{Customer acknowledged completion gate?}
  T7 -- no --> Stop
  T7 -- yes --> T8{Director approved completion gate?}
  T8 -- no --> Stop
  T8 -- yes --> Issue[Director issues numbered IITPL certificate\nHMAC payload + QR code + stored PDF]
  Issue --> Public[Public verification: genuine / revoked / unknown]
  Issue --> Revoke[Director may revoke with reason]
```

## 11. Transactional outbox and asynchronous work

```mermaid
sequenceDiagram
  participant U as User / API
  participant S as Module service
  participant DB as PostgreSQL
  participant W as Celery dispatcher
  participant H as Idempotent subscriber
  participant N as Notification / Search / other module

  U->>S: validated command
  S->>DB: one transaction: change + audit row + outbox row
  DB-->>S: commit
  S-->>U: response
  loop every 5 seconds
    W->>DB: claim due rows FOR UPDATE SKIP LOCKED
    W->>H: deliver event in its own transaction
    H->>N: process side effect
    alt successful
      H->>DB: mark delivered
    else fails
      H->>DB: retry with growing delay
      Note over DB: after 8 attempts: dead for human review
    end
  end
```

## 12. Learning lifecycle — constrained to shadow mode

```mermaid
flowchart LR
  D[BOQ draft] --> Candidates[Persist every ranked candidate\nand its eight criteria]
  A[Customer accepts BOQ] --> Labels[Label candidates kept / not kept]
  Candidates --> Labels
  Labels --> Count{At least 20 accepted groups?}
  Count -- no --> Thin[Training refused; show progress]
  Count -- yes --> Freeze[Freeze immutable numbered training set\nwith data card]
  Freeze --> Train[Train ranker / line predictor / price drift model]
  Train --> Card[Store scores, limits, settings, model card]
  Card --> Shadow[Run beside rules; log agreement and disagreements]
  Shadow -. never alters quotation, verification, waiver, or certificate .-> Human[Human owns all decisions]
  Shadow --> Director{30 days and 20 comparisons\nthen Director approval?}
  Director -- no --> Shadow
  Director -- yes --> Advise[Advice only; person reviews every suggestion]
  Flag[ml_enabled feature flag] -. disables examples, training, shadows, suggestions, alerts .-> Shadow
```

## 13. Persistence and immutability model

```mermaid
flowchart TB
  Mutable[Working records\noptimistic version column] --> Lock[Approved output]
  Lock --> Artifact[Locked stage artifact]
  Lock --> PDF[Stored rendered PDF + checksum]
  Event[Domain change] --> Audit[Append-only hash-chained audit log]
  Event --> Outbox[Transactional outbox]
  Dataset[Dataset version] --> Frozen[Frozen training snapshot]
  Certificate[Issued certificate] --> Immutable[Database-protected immutable record]
  Immutable --> Revocation[Only revocation with reason may change status]
  Audit --> Verify[Audit-log hash-chain verification]
```

## Source map

- Architecture and module boundaries: `docs/ARCHITECTURE.md`
- Stage gates and field states: `backend/app/modules/customers/stages.py`,
  `docs/phases/phase-08-field-operations.md`
- Verification and certificate controls: phases 9–10 and ADRs 0019, 0022, 0025
- BOQ and margin logic: phases 5–6 and ADRs 0021, 0024, 0028
- Learning constraints: phase 13 and ADRs 0020, 0029
