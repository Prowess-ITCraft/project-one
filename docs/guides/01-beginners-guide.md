# Beginner's guide

This guide assumes you have never run a project like this. Follow it top to bottom.

## 1. What you are running

Project One is a **web service** (an API). It has no screens yet; the web app arrives in
phases 11 and 12. Until then you use it through the interactive API page at `/docs`, which
works like a form for every feature.

It is made of several programs that run together in Docker containers:

| Program | What it does | Plain-English role |
| --- | --- | --- |
| api | The FastAPI application | The brain: answers requests |
| worker | Celery worker | Does slow jobs in the background |
| beat | Celery scheduler | The alarm clock: nightly jobs |
| postgres | Database | Stores all records |
| redis | Fast memory store | Rate limits, job queue |
| minio | File storage | Stores uploaded reports, photos |
| clamav | Virus scanner | Checks every upload |
| proxy (nginx) | Front door | The one public entrance |
| prometheus, grafana | Monitoring | Graphs of how healthy it is |
| mailpit | Fake mailbox (dev) | Catches emails so nothing real is sent |
| flower | Job monitor (dev) | Shows background jobs |

## 2. Words you will meet

- **PrismSuite**: the tool that audits a customer's IT and produces a Word report.
- **Audit snapshot**: the clean data Project One extracts from that report.
- **Gap**: a difference between the customer's current IT and the ideal.
- **BOQ**: bill of quantities, the list of items and quantities to fix the gaps.
- **Gate**: an approval step at the end of each of the 8 stages.
- **Artifact**: a locked output (for example an approved audit) that a gate approves.
- **Role**: a job type such as Director or Field engineer. It decides what you may do.
- **MFA**: a second sign-in step using an authenticator app.
- **Migration**: a script that changes the database structure.
- **Outbox**: a safe to-do list of follow-up work saved together with each change.
- **ADR**: a short note explaining a design decision.

## 3. Install the tools (Windows 11)

1. **Docker Desktop**: download from docker.com, install, start it, and wait until it says
   "Engine running". Turn on the WSL 2 option if asked.
2. **Python 3.12**: from python.org. Tick "Add python.exe to PATH".
3. **uv** (a fast Python installer): open PowerShell and run
   `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`.
4. **Git**: from git-scm.com.
5. Check each: `docker --version`, `python --version`, `uv --version`, `git --version`.

## 4. Get the code and install the Python packages

```powershell
cd $HOME\Desktop\project-one\backend
uv sync
```

This creates `backend\.venv` with everything needed to run tests and tools.

## 5. Create your secrets file

Secrets are passwords and keys. They live in a file named `.env` that is never shared.

```powershell
cd $HOME\Desktop\project-one
copy .env.example .env
```

Fill each empty value in `.env`. Generate values with:

```powershell
# passwords and keys
backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(12))"
# P1_JWT_SIGNING_KEYS (longer)
backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
# P1_FERNET_KEYS
backend\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use a different value for every line. For development keep `P1_COOKIE_SECURE=false`.

## 6. Start everything

```powershell
scripts\dev.ps1 up
```

The first run downloads several images and can take 10 to 20 minutes. Afterwards it takes
under a minute. Check progress with `scripts\dev.ps1 ps`; every service should say
`healthy` or `running`.

## 7. Open the pages

| What | Address |
| --- | --- |
| **The web app** (start here) | http://localhost:9597 (or http://localhost:9595) |
| API reference (try features here) | http://localhost:9597/docs |
| Is it alive | http://localhost:9597/healthz |
| Is everything it needs reachable | http://localhost:9597/readyz |
| Grafana graphs (user `admin`, password from `.env`) | http://localhost:9604 |
| Mailpit (caught emails) | http://localhost:9605 |
| Flower (background jobs) | http://localhost:9598 |
| MinIO console (files) | http://localhost:9602 |

## 8. Create the first user and load starter data

```powershell
scripts\dev.ps1 admin --email you@example.com --name "Your Name" --initials YN
scripts\dev.ps1 seed
```

The admin command asks for a password (at least 12 characters, not your name or email).
Admins must set up MFA: in `/docs` call `POST /api/v1/auth/login`; the answer says
`mfa_enrolment_required`. Use `POST /api/v1/auth/mfa/enrol/start` with the challenge token,
add the secret to an authenticator app (Google Authenticator, Microsoft Authenticator),
then `POST /api/v1/auth/mfa/enrol/confirm` with the 6 digit code. Save the recovery codes.

`seed` loads the catalogue items and prices taken from the two sample BOQs.

## 9. A guided tour in the web app (10 minutes)

Open http://localhost:9597 and sign in with the admin you created. Then:

1. **Users**: create a Solution architect, an Audit engineer, a Technical lead and a Sales head.
2. Sign out, sign in as the Sales head. **Projects, New project**: name it and add a customer.
3. On the project page, **Team**: add the architect, the audit engineer and the technical lead.
4. Sign in as the audit engineer. **Audit reports, Upload and import** with the Shakti file from `samples`.
5. Open the revision. Under **Needs your attention**, review the firewall conflict and confirm it with a reason.
6. Sign in as the architect: open the revision and **Approve and lock**.
7. On the project page choose **Submit for approval**. Sign in as the technical lead and **Approve stage**. The stage rail moves to Current IT.
8. **Catalogue, Prices to refresh**: open an item and enter a new price.
9. Back on the project, open the **Questionnaire** tab and save the customer's size, tier and brands.
10. **Infrastructure** tab: build the current state, lock it, build the ideal state, lock it.
11. **Gaps** tab: draft the register, decide every verify item, lock it.
12. **BOQ** tab: draft the BOQ. Type a price (with its source) for any line the price book lacks. Edit, add or delete lines as the Director would, then **Save changes** with a reason.
13. Submit for pricing review. Sign in as another sales head, **Approve pricing**, then **Issue as a new version** and open the PDF.
    Once there are two versions, **Compare versions** under the list shows the lines added, removed and changed
    between any two, with both totals.
14. Record the customer PO to accept the BOQ. Then the **Plan** tab: **Draft the plan**, add a downtime window,
    **Schedule the plan**, and as the technical lead **Lock plan**. **Download plan (PDF)** shows the schedule.
15. After the plan stage is approved, the **Field work** tab: **Start field work**. Each engineer is emailed their list.
16. Sign in as a field engineer on a phone (or a narrow window). **My tasks** opens. Open a task and follow the
    sentence under the timeline: accept, take the site photo, send the code to the customer and type it in, confirm
    backup and access, tick the steps, type what the device shows, add the evidence, send it for the check, then
    get the hand over code. With no signal, work is kept on the phone and sent later.
    To install it like an app: open the site in Chrome on the phone, then menu, **Add to Home screen**. It opens
    on **My tasks**, and a task page that was opened earlier still opens with no signal.
17. Sign in as a technical lead (not the engineer). **Review** lists the handed over task. Open it, then **Approve
    and close** or **Send back** with what must be fixed. The Director sees every change live on the Field work tab.
18. **Library**: drop the two BOQ PDFs from `samples`. **Files** shows what was read and the one repaired line to
    confirm; **Corpus** shows each document converted to compact data; **Data quality** shows labels and price bands.
    **Before the approvals:** once the report is uploaded and the Questionnaire is saved, **Draft BOQ
    estimate** (on those tabs or the BOQ tab) shows what the BOQ will roughly contain and cost, with PDF and
    Excel. It is marked Not approved and saved nowhere; the official BOQ still comes after the gates.
19. When field work is finished, the project manager opens the **Completion** tab: lock the field work summary,
    import the after-work PrismSuite rescan, then preview and lock the completion report. The tab lists the eight
    conditions and says exactly what is still missing for each.
20. Sign in as the Director: **Dashboard** shows every project, blocked work and open deviations. On the
    **Completion** tab, approve the stage, then **Issue certificate**. Anyone can scan its QR code to check it.

### The demo data

`python -m app.cli demo-projects` builds two projects through the API, one finished with a certificate and one
part way through field work, using the ITCraft / IITPL team as the staff accounts (Satish Agadi as Director,
Akash Agadii as Sales head, Ashwini Sawant as Project manager, Yash Raikar and Sakshi Rajbhar as field engineers,
and so on). It writes the shared password and the authenticator secrets to `demo-accounts.json`. Because the
accounts use real work addresses, it refuses to run unless outgoing mail goes to Mailpit.

For quick testing in development, `python -m app.cli seed-demo` creates the demo user `adi@test.com` (password `test1234`). It holds Admin and every role except Director, so the first sign-in asks you to set up an authenticator app: scan the QR code, type the 6 digit code and save the recovery codes. On `localhost` the sign-in page offers a **Fill in** button for this login. The command refuses to run outside development.

The same tour through the raw API follows, for people who prefer it.

### The same tour through the API (15 minutes)

1. **Sign in** at `/docs`: click Authorize and use the access token from login.
2. **Create users** for each role with `POST /api/v1/users` (one Audit engineer, one
   Solution architect, one Sales manager, one Sales head, one Technical lead).
3. **Create a customer** (`POST /customers`) and a **project** (`POST /projects`, needs an
   `Idempotency-Key` header: any random 16 to 128 character text).
4. **Add team members** to the project (`PUT /projects/{id}/members`).
5. **Upload the audit**: as the Audit engineer call `POST /files` with purpose
   `audit_report`, the project id and the Shakti report from `samples/`.
6. **Import it**: `POST /prismsuite/imports` with the file id. Read the result at
   `GET /prismsuite/imports/{id}`: scores, counts, and the read report.
7. **Review**: confirm the firewall high availability conflict with
   `POST /prismsuite/imports/{id}/resolutions`.
8. **Approve** as a different person (`POST .../approve`). The project now has a locked audit.
9. **Submit the gate** (`POST /projects/{id}/stages/audit_intake/submit`) and approve it
   as a Technical lead. The project moves to Current infrastructure.
10. **Look at the price book**: `GET /catalogue/prices/attention` lists prices that need
    refreshing.

## 10. Stop and clean up

```powershell
scripts\dev.ps1 down          # stop, keep data
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v   # stop and delete all data
```

## 11. Run the tests

```powershell
scripts\dev.ps1 test
```

The tests start their own throwaway database, cache and storage containers, so Docker must
be running. About 100 tests take 2 to 3 minutes.

## 12. When something goes wrong

| Symptom | Likely cause and fix |
| --- | --- |
| `docker: error during connect` | Docker Desktop is not running. Start it and wait for "Engine running". |
| A variable `is required` when starting | A value is missing in `.env`. Fill it. |
| `/readyz` says not ready | Wait a minute, then `scripts\dev.ps1 ps` and `scripts\dev.ps1 logs`. |
| Sign-in says too many requests | The rate limiter protects sign-in. Wait a minute. |
| Sign-in says locked | Five wrong passwords lock the account. An Admin can unlock it. |
| 403 on an endpoint | Your role lacks the permission. See the role table in the developer guide. |
| 409 "Someone else changed this record" | Reload the record and resend with its new `version`. |
| Image download fails or stalls | Retry `scripts\dev.ps1 up`. If Docker reports a storage error, restart Docker Desktop. |
| Tests cannot start containers | Docker is not running, or the disk is full. |

## 13. Safety rules for beginners

- Never commit `.env` or paste its content anywhere.
- Never use development passwords on a real server.
- Do not turn off the virus scanner or rate limits to make something work.
- Ask before changing anything that touches prices, certificates or who can approve.
