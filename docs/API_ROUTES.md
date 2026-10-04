# API routes

All 253 operations of the Project One API, grouped by area. Generated from the
code with `python -m app.cli api-routes`; do not edit by hand. The interactive
reference, where you can try each call, is at `/docs` on a running server;
conventions, errors and sign-in are in the [API guide](guides/04-api-guide.md).

"Sign-in" means the call needs a signed-in user (a bearer token or the session cookie);
what each role may call is in the permission matrix test.

## Admin

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/admin/feature-flags` | List Flags | yes |
| PUT | `/api/v1/admin/feature-flags/{key}` | Set Flag | yes |

## Audit log

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/audit-log` | List Entries | yes |
| GET | `/api/v1/audit-log/verify` | Check the hash chain for tampering | yes |

## Auth

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | Sign in | no |
| POST | `/api/v1/auth/logout` | Sign out of this session | yes |
| GET | `/api/v1/auth/me` | Me | yes |
| POST | `/api/v1/auth/mfa/enrol/confirm` | Confirm MFA set-up | yes |
| POST | `/api/v1/auth/mfa/enrol/start` | Start MFA set-up | yes |
| POST | `/api/v1/auth/mfa/verify` | Finish sign-in with an MFA code | no |
| POST | `/api/v1/auth/password` | Change your password | yes |
| POST | `/api/v1/auth/refresh` | Swap a refresh token for new tokens | no |
| GET | `/api/v1/auth/sessions` | Your active sessions | yes |
| POST | `/api/v1/auth/sessions/revoke-others` | Revoke Other Sessions | yes |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Revoke My Session | yes |
| POST | `/api/v1/auth/token` | Sign in (OAuth2 form, for /docs) | no |

## Boq

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/boq/company` | Get Company | yes |
| PUT | `/api/v1/boq/company` | Put Company | yes |
| GET | `/api/v1/boq/templates` | List Templates | yes |
| PUT | `/api/v1/boq/templates/{gap_type}` | Put Template | yes |
| GET | `/api/v1/boq/weights/{segment}` | Get Weights | yes |
| PUT | `/api/v1/boq/weights/{segment}` | Put Weights | yes |
| GET | `/api/v1/boq/{boq_id}` | Get Boq | yes |
| POST | `/api/v1/boq/{boq_id}/add-item` | Add Item | yes |
| GET | `/api/v1/boq/{boq_id}/compare` | Compare | yes |
| POST | `/api/v1/boq/{boq_id}/edit` | Edit | yes |
| GET | `/api/v1/boq/{boq_id}/edits` | Edits | yes |
| POST | `/api/v1/boq/{boq_id}/issue` | Issue | yes |
| GET | `/api/v1/boq/{boq_id}/lines/{line_id}/history` | Line History | yes |
| POST | `/api/v1/boq/{boq_id}/pricing-decision` | Pricing Decision | yes |
| GET | `/api/v1/boq/{boq_id}/recommend` | Recommend | yes |
| POST | `/api/v1/boq/{boq_id}/refresh-prices` | Refresh Prices | yes |
| GET | `/api/v1/boq/{boq_id}/render` | Render Doc | yes |
| POST | `/api/v1/boq/{boq_id}/reopen` | Reopen | yes |
| POST | `/api/v1/boq/{boq_id}/submit` | Submit | yes |
| GET | `/api/v1/boq/{boq_id}/versions` | Versions | yes |
| GET | `/api/v1/boq/{boq_id}/versions/{number}` | Get Version | yes |
| POST | `/api/v1/boq/{boq_id}/versions/{number}/accept` | Accept | yes |
| GET | `/api/v1/projects/{project_id}/boq` | Get Project Boq | yes |
| GET | `/api/v1/projects/{project_id}/boq/estimate` | Estimate | yes |
| POST | `/api/v1/projects/{project_id}/boq/generate` | Generate | yes |

## Catalogue

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/catalogue/categories` | Categories | yes |
| GET | `/api/v1/catalogue/items` | List Items | yes |
| POST | `/api/v1/catalogue/items` | Create Item | yes |
| GET | `/api/v1/catalogue/items/{item_id}` | Get Item | yes |
| PATCH | `/api/v1/catalogue/items/{item_id}` | Update Item | yes |
| DELETE | `/api/v1/catalogue/items/{item_id}` | Delete Item | yes |
| GET | `/api/v1/catalogue/items/{item_id}/market-data` | Market Data | yes |
| POST | `/api/v1/catalogue/items/{item_id}/market-data` | Add Market Data | yes |
| GET | `/api/v1/catalogue/items/{item_id}/price` | Current Price | yes |
| GET | `/api/v1/catalogue/items/{item_id}/prices` | Price History | yes |
| POST | `/api/v1/catalogue/items/{item_id}/prices` | Add Price | yes |
| POST | `/api/v1/catalogue/items/{item_id}/stock` | Set Stock | yes |
| GET | `/api/v1/catalogue/prices/attention` | Price Attention | yes |
| GET | `/api/v1/catalogue/prices/current` | Current Prices | yes |
| GET | `/api/v1/catalogue/vendors` | Vendors | yes |
| POST | `/api/v1/catalogue/vendors` | Create Vendor | yes |
| PATCH | `/api/v1/catalogue/vendors/{vendor_id}` | Update Vendor | yes |

## Customers

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/customers` | List Customers | yes |
| POST | `/api/v1/customers` | Create Customer | yes |
| GET | `/api/v1/customers/{customer_id}` | Get Customer | yes |
| PATCH | `/api/v1/customers/{customer_id}` | Update Customer | yes |
| DELETE | `/api/v1/customers/{customer_id}` | Delete Customer | yes |
| GET | `/api/v1/customers/{customer_id}/contacts` | List Contacts | yes |
| POST | `/api/v1/customers/{customer_id}/contacts` | Add Contact | yes |
| PATCH | `/api/v1/customers/{customer_id}/contacts/{contact_id}` | Update Contact | yes |
| DELETE | `/api/v1/customers/{customer_id}/contacts/{contact_id}` | Delete Contact | yes |
| POST | `/api/v1/customers/{customer_id}/contacts/{contact_id}/restore` | Restore Contact | yes |
| POST | `/api/v1/customers/{customer_id}/representatives` | Create a customer representative account (sign-in stays off until the flag is on) | yes |
| POST | `/api/v1/customers/{customer_id}/restore` | Restore Customer | yes |
| GET | `/api/v1/customers/{customer_id}/sites` | List Sites | yes |
| POST | `/api/v1/customers/{customer_id}/sites` | Add Site | yes |
| PATCH | `/api/v1/customers/{customer_id}/sites/{site_id}` | Update Site | yes |
| DELETE | `/api/v1/customers/{customer_id}/sites/{site_id}` | Delete Site | yes |
| POST | `/api/v1/customers/{customer_id}/sites/{site_id}/restore` | Restore Site | yes |

## Datasets

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/datasets` | List Datasets | yes |
| POST | `/api/v1/datasets/from-import` | Create From Import | yes |
| POST | `/api/v1/datasets/from-rows` | Create From Rows | yes |
| POST | `/api/v1/datasets/import-preview` | Import Preview | yes |
| GET | `/api/v1/datasets/promotions` | Promotions | yes |
| POST | `/api/v1/datasets/promotions/{promotion_id}/decision` | Decide Promotion | yes |
| GET | `/api/v1/datasets/synonyms` | Synonyms | yes |
| POST | `/api/v1/datasets/synonyms` | Add Synonym | yes |
| GET | `/api/v1/datasets/{dataset_id}` | Get Dataset | yes |
| PATCH | `/api/v1/datasets/{dataset_id}` | Update Dataset | yes |
| DELETE | `/api/v1/datasets/{dataset_id}` | Delete Dataset | yes |
| GET | `/api/v1/datasets/{dataset_id}/analysis` | Analysis | yes |
| GET | `/api/v1/datasets/{dataset_id}/chart` | Chart | yes |
| GET | `/api/v1/datasets/{dataset_id}/diff` | Diff | yes |
| POST | `/api/v1/datasets/{dataset_id}/duplicate` | Duplicate | yes |
| GET | `/api/v1/datasets/{dataset_id}/export` | Export | yes |
| POST | `/api/v1/datasets/{dataset_id}/freeze` | Freeze | yes |
| POST | `/api/v1/datasets/{dataset_id}/pipeline` | Run Pipeline | yes |
| POST | `/api/v1/datasets/{dataset_id}/promotions` | Submit Promotions | yes |
| GET | `/api/v1/datasets/{dataset_id}/quarantine` | Quarantine | yes |
| POST | `/api/v1/datasets/{dataset_id}/quarantine/{row_id}` | Resolve Quarantine | yes |
| POST | `/api/v1/datasets/{dataset_id}/restore` | Restore Dataset | yes |
| GET | `/api/v1/datasets/{dataset_id}/rows` | Rows | yes |
| POST | `/api/v1/datasets/{dataset_id}/rows` | Append Rows | yes |
| GET | `/api/v1/datasets/{dataset_id}/shares` | Shares | yes |
| PUT | `/api/v1/datasets/{dataset_id}/shares` | Share | yes |
| DELETE | `/api/v1/datasets/{dataset_id}/shares/{kind}/{target}` | Unshare | yes |
| GET | `/api/v1/datasets/{dataset_id}/versions` | Versions | yes |

## Field work

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/field/my` | My Tasks | yes |
| GET | `/api/v1/field/review-queue` | Review Queue | yes |
| GET | `/api/v1/field/runs/{run_id}` | Run Detail | yes |
| POST | `/api/v1/field/runs/{run_id}/accept` | Accept | yes |
| POST | `/api/v1/field/runs/{run_id}/block` | Block | yes |
| POST | `/api/v1/field/runs/{run_id}/check-in` | Check In | yes |
| POST | `/api/v1/field/runs/{run_id}/codes/{purpose}` | Send Code | yes |
| POST | `/api/v1/field/runs/{run_id}/configured` | Configured | yes |
| POST | `/api/v1/field/runs/{run_id}/decision` | Decision | yes |
| POST | `/api/v1/field/runs/{run_id}/depart` | Depart | yes |
| POST | `/api/v1/field/runs/{run_id}/evidence` | Add Evidence | yes |
| POST | `/api/v1/field/runs/{run_id}/hand-over` | Hand Over | yes |
| POST | `/api/v1/field/runs/{run_id}/prechecks-done` | Prechecks Done | yes |
| POST | `/api/v1/field/runs/{run_id}/reassign` | Reassign | yes |
| GET | `/api/v1/field/runs/{run_id}/render` | Render Checklist | yes |
| POST | `/api/v1/field/runs/{run_id}/steps/{index}` | Step Done | yes |
| POST | `/api/v1/field/runs/{run_id}/submit-evidence` | Submit Evidence | yes |
| POST | `/api/v1/field/runs/{run_id}/unblock` | Unblock | yes |
| POST | `/api/v1/field/runs/{run_id}/values` | Record Values | yes |
| GET | `/api/v1/projects/{project_id}/field/events` | Project Events | yes |
| GET | `/api/v1/projects/{project_id}/field/runs` | Project Runs | yes |
| POST | `/api/v1/projects/{project_id}/field/start` | Start | yes |
| GET | `/api/v1/projects/{project_id}/field/stream` | Project Stream | yes |
| GET | `/api/v1/projects/{project_id}/field/summary` | Project Summary | yes |

## Files

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| POST | `/api/v1/files` | Upload a file | yes |
| GET | `/api/v1/files/{file_id}` | Get File | yes |
| GET | `/api/v1/files/{file_id}/download` | Short-lived download link | yes |

## Infra

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/infra/rules` | List Rules | yes |
| GET | `/api/v1/infra/rules/changes` | List Changes | yes |
| POST | `/api/v1/infra/rules/changes` | Propose Change | yes |
| POST | `/api/v1/infra/rules/changes/{change_id}/decision` | Decide Change | yes |
| GET | `/api/v1/infra/rules/facts` | Facts | yes |
| GET | `/api/v1/infra/rules/{rule_id}` | Get Rule | yes |
| GET | `/api/v1/projects/{project_id}/gaps` | Get Gaps | yes |
| POST | `/api/v1/projects/{project_id}/gaps` | Generate Gaps | yes |
| POST | `/api/v1/projects/{project_id}/gaps/{register_id}/items` | Add Gap | yes |
| PATCH | `/api/v1/projects/{project_id}/gaps/{register_id}/items/{gap_id}` | Update Gap | yes |
| POST | `/api/v1/projects/{project_id}/gaps/{register_id}/lock` | Lock Gaps | yes |
| GET | `/api/v1/projects/{project_id}/infra` | List States | yes |
| POST | `/api/v1/projects/{project_id}/infra/current` | Build Current | yes |
| POST | `/api/v1/projects/{project_id}/infra/ideal` | Build Ideal | yes |
| POST | `/api/v1/projects/{project_id}/infra/{state_id}/lock` | Lock State | yes |

## Learning

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/ml/models` | Models | yes |
| POST | `/api/v1/ml/models` | Train | yes |
| POST | `/api/v1/ml/models/{model_id}/status` | Set Status | yes |
| GET | `/api/v1/ml/report` | Report | yes |
| GET | `/api/v1/ml/training-sets` | Training Sets | yes |
| POST | `/api/v1/ml/training-sets` | Freeze | yes |

## Library

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/library/analysis` | Corpus Analysis | yes |
| GET | `/api/v1/library/collections` | Library Collections | yes |
| GET | `/api/v1/library/corpus` | Corpus List | yes |
| GET | `/api/v1/library/corpus/{doc_id}` | Corpus Get | yes |
| GET | `/api/v1/library/files` | Library Files | yes |
| POST | `/api/v1/library/files` | Library Upload | yes |
| POST | `/api/v1/library/files/{library_file_id}/retry` | Library Retry | yes |
| POST | `/api/v1/library/rebuild` | Corpus Rebuild | yes |

## Notifications

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/account/notification-preferences` | Preferences | yes |
| PUT | `/api/v1/account/notification-preferences/{template}` | Set Preference | yes |
| GET | `/api/v1/notifications` | List Notifications | yes |

## Planning

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/planning/config-templates` | Config Templates | yes |
| GET | `/api/v1/planning/leaves` | Leaves | yes |
| POST | `/api/v1/planning/leaves` | Add Leave | yes |
| DELETE | `/api/v1/planning/leaves/{leave_id}` | Remove Leave | yes |
| GET | `/api/v1/planning/task-templates` | Task Templates | yes |
| PATCH | `/api/v1/planning/task-templates/{key}` | Patch Task Template | yes |
| GET | `/api/v1/projects/{project_id}/plan` | Get Plan | yes |
| PATCH | `/api/v1/projects/{project_id}/plan/baselines/{baseline_id}` | Patch Baseline | yes |
| POST | `/api/v1/projects/{project_id}/plan/downtime` | Add Window | yes |
| DELETE | `/api/v1/projects/{project_id}/plan/downtime/{window_id}` | Remove Window | yes |
| POST | `/api/v1/projects/{project_id}/plan/generate` | Generate | yes |
| GET | `/api/v1/projects/{project_id}/plan/render` | Render Plan | yes |
| POST | `/api/v1/projects/{project_id}/plan/schedule` | Schedule | yes |
| POST | `/api/v1/projects/{project_id}/plan/tasks` | Create Task | yes |
| PATCH | `/api/v1/projects/{project_id}/plan/tasks/{task_id}` | Patch Task | yes |
| DELETE | `/api/v1/projects/{project_id}/plan/tasks/{task_id}` | Remove Task | yes |
| POST | `/api/v1/projects/{project_id}/plan/{plan_id}/baseline` | Baseline | yes |

## Prismsuite

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| POST | `/api/v1/prismsuite/imports` | Create Import | yes |
| GET | `/api/v1/prismsuite/imports/by-project/{project_id}` | List For Project | yes |
| GET | `/api/v1/prismsuite/imports/{import_id}` | Get Import | yes |
| POST | `/api/v1/prismsuite/imports/{import_id}/approve` | Approve | yes |
| POST | `/api/v1/prismsuite/imports/{import_id}/corrections` | Add Correction | yes |
| POST | `/api/v1/prismsuite/imports/{import_id}/reject` | Reject | yes |
| POST | `/api/v1/prismsuite/imports/{import_id}/resolutions` | Resolve Field | yes |

## Projects

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/gates` | List Gate Configs | yes |
| PUT | `/api/v1/gates/{stage}` | Update Gate Config | yes |
| GET | `/api/v1/projects` | List Projects | yes |
| POST | `/api/v1/projects` | Create Project | yes |
| GET | `/api/v1/projects/{project_id}` | Get Project | yes |
| PATCH | `/api/v1/projects/{project_id}` | Update Project | yes |
| DELETE | `/api/v1/projects/{project_id}` | Delete Project | yes |
| GET | `/api/v1/projects/{project_id}/artifacts` | List Artifacts | yes |
| GET | `/api/v1/projects/{project_id}/brief` | Get Brief | yes |
| PUT | `/api/v1/projects/{project_id}/brief` | Put Brief | yes |
| GET | `/api/v1/projects/{project_id}/gate-history` | Gate History | yes |
| GET | `/api/v1/projects/{project_id}/members` | List Members | yes |
| PUT | `/api/v1/projects/{project_id}/members` | Set Member | yes |
| DELETE | `/api/v1/projects/{project_id}/members/{user_id}` | Remove Member | yes |
| POST | `/api/v1/projects/{project_id}/restore` | Restore Project | yes |
| POST | `/api/v1/projects/{project_id}/return-to/{stage}` | Return To Stage | yes |
| POST | `/api/v1/projects/{project_id}/stages/{stage}/submit` | Submit Stage | yes |
| POST | `/api/v1/projects/{project_id}/submissions/{submission_id}/approve` | Approve | yes |
| POST | `/api/v1/projects/{project_id}/submissions/{submission_id}/customer-ack` | Create a single-use acknowledgement link for a customer contact | yes |
| POST | `/api/v1/projects/{project_id}/submissions/{submission_id}/reject` | Reject | yes |
| POST | `/api/v1/projects/{project_id}/submissions/{submission_id}/withdraw` | Withdraw | yes |
| GET | `/api/v1/projects/{project_id}/tracker` | Stage tracker | yes |

## Public

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/public/acks/{token}` | View Ack | no |
| POST | `/api/v1/public/acks/{token}` | Confirm Ack | no |
| GET | `/api/v1/public/certificates/{number}` | Verify Certificate | no |
| GET | `/api/v1/public/files/{file_id}` | Open a file through a signed download link | no |
| GET | `/api/v1/public/waivers/{token}` | View Waiver | no |
| POST | `/api/v1/public/waivers/{token}` | Acknowledge Waiver | no |

## Reporting

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/reporting/certificates/{certificate_id}/pdf` | Certificate Pdf | yes |
| POST | `/api/v1/reporting/certificates/{certificate_id}/revoke` | Revoke | yes |
| GET | `/api/v1/reporting/projects/{project_id}/certificates` | Certificates | yes |
| POST | `/api/v1/reporting/projects/{project_id}/certificates` | Issue | yes |
| GET | `/api/v1/reporting/projects/{project_id}/conditions` | Release Conditions | yes |
| POST | `/api/v1/reporting/projects/{project_id}/field-summary` | Lock Field Summary | yes |
| GET | `/api/v1/reporting/projects/{project_id}/report/preview` | Report Preview | yes |
| GET | `/api/v1/reporting/projects/{project_id}/reports` | Reports | yes |
| POST | `/api/v1/reporting/projects/{project_id}/reports` | Lock Report | yes |
| GET | `/api/v1/reporting/projects/{project_id}/waivers` | Waivers | yes |
| POST | `/api/v1/reporting/projects/{project_id}/waivers` | Request Waiver | yes |
| GET | `/api/v1/reporting/reports/{report_id}/pdf` | Report Pdf | yes |
| GET | `/api/v1/reporting/settings` | Certificate Settings | yes |
| GET | `/api/v1/reporting/settings/stamp` | Get Stamp | yes |
| POST | `/api/v1/reporting/settings/stamp` | Put Stamp | yes |
| PUT | `/api/v1/reporting/settings/wording` | Put Wording | yes |
| POST | `/api/v1/reporting/waivers/{waiver_id}/decision` | Decide Waiver | yes |

## Users

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/roles` | Roles and their permissions | yes |
| GET | `/api/v1/users` | List Users | yes |
| POST | `/api/v1/users` | Create User | yes |
| GET | `/api/v1/users/{user_id}` | Get User | yes |
| PATCH | `/api/v1/users/{user_id}` | Update User | yes |
| POST | `/api/v1/users/{user_id}/erase` | Erase personal data (GDPR) | yes |
| POST | `/api/v1/users/{user_id}/reset-mfa` | Reset Mfa | yes |
| POST | `/api/v1/users/{user_id}/reset-password` | Reset Password | yes |
| PUT | `/api/v1/users/{user_id}/roles` | Set Roles | yes |
| GET | `/api/v1/users/{user_id}/sessions` | User Sessions | yes |
| POST | `/api/v1/users/{user_id}/sessions/revoke-all` | Revoke User Sessions | yes |
| DELETE | `/api/v1/users/{user_id}/sessions/{session_id}` | Revoke User Session | yes |
| POST | `/api/v1/users/{user_id}/unlock` | Unlock User | yes |

## Verification

| Method | Path | What it does | Sign-in |
| --- | --- | --- | --- |
| GET | `/api/v1/dashboard` | Dashboard | yes |
| POST | `/api/v1/verification/deviations` | Add Deviation | yes |
| POST | `/api/v1/verification/deviations/{deviation_id}/accept` | Accept | yes |
| POST | `/api/v1/verification/inspect` | Inspect | yes |
| GET | `/api/v1/verification/mappings` | Mappings | yes |
| PATCH | `/api/v1/verification/mappings/{map_id}` | Patch Mapping | yes |
| GET | `/api/v1/verification/policy` | Get Policy | yes |
| PUT | `/api/v1/verification/policy` | Put Policy | yes |
| GET | `/api/v1/verification/projects/{project_id}/deviations` | Deviations | yes |
