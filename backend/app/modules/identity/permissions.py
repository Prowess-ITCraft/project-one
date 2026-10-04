"""Roles and the permission matrix. Deny by default: a permission not listed is not granted.

A person may hold several roles; their permissions are the union. Segregation of duties
(doer != verifier) is enforced separately in services, per action, not through this matrix.
Field engineers hold no price permission. Field-work responses never include prices even for
people who also hold a sales role (enforced by the field ops schemas in Phase 8).
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    AUDIT_ENGINEER = "audit_engineer"
    SOLUTION_ARCHITECT = "solution_architect"
    TECHNICAL_LEAD = "technical_lead"
    SALES_MANAGER = "sales_manager"
    SALES_HEAD = "sales_head"
    PROJECT_MANAGER = "project_manager"
    FIELD_ENGINEER = "field_engineer"
    DIRECTOR = "director"
    CUSTOMER_REP = "customer_rep"
    ADMIN = "admin"


ROLE_LABELS: dict[Role, str] = {
    Role.AUDIT_ENGINEER: "Audit engineer",
    Role.SOLUTION_ARCHITECT: "Solution architect",
    Role.TECHNICAL_LEAD: "Technical lead / verifier",
    Role.SALES_MANAGER: "Sales / BD manager",
    Role.SALES_HEAD: "Sales head",
    Role.PROJECT_MANAGER: "Project manager",
    Role.FIELD_ENGINEER: "Field engineer",
    Role.DIRECTOR: "Director",
    Role.CUSTOMER_REP: "Customer representative",
    Role.ADMIN: "Admin",
}

MFA_REQUIRED_ROLES = frozenset({Role.DIRECTOR, Role.ADMIN})
STAFF_ROLES = frozenset(r for r in Role if r is not Role.CUSTOMER_REP)


class P(StrEnum):
    """Permission codes. Stable strings: they appear in tokens of tests and docs."""

    USER_READ = "user:read"
    USER_MANAGE = "user:manage"
    SESSION_MANAGE_ANY = "session:manage_any"
    AUDIT_READ = "audit:read"
    AUDIT_VERIFY = "audit:verify"
    PERSONAL_DATA_ERASE = "personal_data:erase"
    FLAGS_MANAGE = "flags:manage"

    CUSTOMER_READ = "customer:read"
    CUSTOMER_READ_ALL = "customer:read_all"
    CUSTOMER_WRITE = "customer:write"
    CUSTOMER_DELETE = "customer:delete"

    PROJECT_READ = "project:read"
    PROJECT_READ_ALL = "project:read_all"
    PROJECT_WRITE = "project:write"
    BRIEF_WRITE = "brief:write"  # the intake questionnaire; also audit engineers (ADR 0024)
    PROJECT_MEMBERS = "project:manage_members"
    PROJECT_DELETE = "project:delete"

    GATE_SUBMIT = "gate:submit"
    GATE_APPROVE = "gate:approve"
    GATE_CONFIGURE = "gate:configure"
    CUSTOMER_ACK_ISSUE = "customer_ack:issue"

    FILE_UPLOAD = "file:upload"
    FILE_READ = "file:read"

    PRISMSUITE_READ = "prismsuite:read"  # the list of a project's imports, status only
    PRISMSUITE_IMPORT = "prismsuite:import"
    PRISMSUITE_REVIEW = "prismsuite:review"
    PRISMSUITE_APPROVE = "prismsuite:approve"

    CATALOGUE_READ = "catalogue:read"
    CATALOGUE_WRITE = "catalogue:write"
    PRICE_READ = "price:read"
    PRICE_WRITE = "price:write"

    DATASET_READ = "dataset:read"
    DATASET_WRITE = "dataset:write"
    DATASET_ADMIN = "dataset:admin"

    INFRA_READ = "infra:read"
    INFRA_WRITE = "infra:write"
    RULE_EDIT = "rule:edit"
    RULE_APPROVE = "rule:approve"

    BOQ_READ = "boq:read"
    BOQ_EDIT = "boq:edit"
    # The estimate straight from the PrismSuite report: saved nowhere, so it needs less than
    # editing a BOQ. Audit engineers hold it too (ADR 0024).
    BOQ_ESTIMATE = "boq:estimate"
    BOQ_APPROVE_PRICING = "boq:approve_pricing"
    BOQ_ISSUE = "boq:issue"
    BOQ_ACCEPT = "boq:accept"
    TEMPLATE_EDIT = "template:edit"
    SETTINGS_EDIT = "settings:edit"

    PLAN_READ = "plan:read"
    PLAN_WRITE = "plan:write"
    PLAN_BASELINE = "plan:baseline"

    # Field work (phase 8). Work: the assigned engineer's actions. Manage: start, reassign,
    # unblock. Verify: approve or send back finished work (never the engineer who did it).
    FIELD_READ = "field:read"
    FIELD_WORK = "field:work"
    FIELD_MANAGE = "field:manage"
    FIELD_VERIFY = "field:verify"

    # Verification and the Director's dashboard (phase 9).
    DASHBOARD_READ = "dashboard:read"
    POLICY_EDIT = "policy:edit"

    # Completion report, waivers and the certificate (phase 10). Only the Director approves
    # waivers and issues the certificate (ADR 0019).
    REPORT_READ = "report:read"
    REPORT_WRITE = "report:write"
    WAIVER_APPROVE = "waiver:approve"
    CERT_ISSUE = "certificate:issue"
    CERT_SETTINGS = "certificate:settings"

    # Learning from accepted BOQs (phase 13). The ranker only runs in shadow mode (ADR 0020).
    ML_READ = "ml:read"
    ML_MANAGE = "ml:manage"


_READ_WORK = {P.CUSTOMER_READ, P.PROJECT_READ, P.FILE_READ, P.CATALOGUE_READ}

ROLE_PERMISSIONS: dict[Role, frozenset[P]] = {
    Role.ADMIN: frozenset(
        {
            P.ML_READ,
            P.ML_MANAGE,
            P.POLICY_EDIT,
            P.CERT_SETTINGS,
            P.PLAN_READ,
            P.USER_READ,
            P.USER_MANAGE,
            P.SESSION_MANAGE_ANY,
            P.AUDIT_READ,
            P.AUDIT_VERIFY,
            P.PERSONAL_DATA_ERASE,
            P.FLAGS_MANAGE,
            P.GATE_CONFIGURE,
            P.CUSTOMER_READ,
            P.CUSTOMER_READ_ALL,
            P.CUSTOMER_DELETE,
            P.PROJECT_READ,
            P.PROJECT_READ_ALL,
            P.PROJECT_MEMBERS,
            P.PROJECT_DELETE,
            P.FILE_READ,
            P.CATALOGUE_READ,
            P.CATALOGUE_WRITE,
            P.DATASET_READ,
            P.DATASET_WRITE,
            P.DATASET_ADMIN,
            P.INFRA_READ,
            P.RULE_EDIT,
            P.TEMPLATE_EDIT,
            P.SETTINGS_EDIT,
        }
    ),
    Role.DIRECTOR: frozenset(
        {
            P.ML_READ,
            P.ML_MANAGE,
            P.DASHBOARD_READ,
            P.POLICY_EDIT,
            P.REPORT_READ,
            P.REPORT_WRITE,
            P.WAIVER_APPROVE,
            P.CERT_ISSUE,
            P.CERT_SETTINGS,
            P.FIELD_READ,
            P.FIELD_MANAGE,
            P.FIELD_VERIFY,
            P.PLAN_READ,
            P.PLAN_WRITE,
            P.PLAN_BASELINE,
            P.USER_READ,
            P.AUDIT_READ,
            P.CUSTOMER_READ,
            P.CUSTOMER_READ_ALL,
            P.CUSTOMER_WRITE,
            P.PROJECT_READ,
            P.PROJECT_READ_ALL,
            P.PROJECT_WRITE,
            P.BRIEF_WRITE,
            P.PROJECT_MEMBERS,
            P.GATE_SUBMIT,
            P.GATE_APPROVE,
            P.CUSTOMER_ACK_ISSUE,
            P.FILE_UPLOAD,
            P.PRISMSUITE_READ,
            P.PRISMSUITE_IMPORT,
            P.FILE_READ,
            P.PRISMSUITE_REVIEW,
            P.PRISMSUITE_APPROVE,
            P.CATALOGUE_READ,
            P.PRICE_READ,
            P.DATASET_READ,
            P.DATASET_ADMIN,
            P.INFRA_READ,
            P.INFRA_WRITE,
            P.RULE_APPROVE,
            P.BOQ_READ,
            P.BOQ_EDIT,
            P.BOQ_ESTIMATE,
            P.BOQ_APPROVE_PRICING,
            P.BOQ_ISSUE,
            P.BOQ_ACCEPT,
            P.TEMPLATE_EDIT,
        }
    ),
    Role.SALES_HEAD: frozenset(
        {
            P.ML_READ,
            P.DASHBOARD_READ,
            P.REPORT_READ,
            *_READ_WORK,
            P.USER_READ,
            P.CUSTOMER_READ_ALL,
            P.CUSTOMER_WRITE,
            P.PROJECT_READ_ALL,
            P.PROJECT_WRITE,
            P.BRIEF_WRITE,
            P.PROJECT_MEMBERS,
            P.GATE_SUBMIT,
            P.GATE_APPROVE,
            P.CUSTOMER_ACK_ISSUE,
            P.FILE_UPLOAD,
            P.PRISMSUITE_READ,
            P.PRISMSUITE_IMPORT,
            P.CATALOGUE_WRITE,
            P.PRICE_READ,
            P.PRICE_WRITE,
            P.DATASET_READ,
            P.DATASET_WRITE,
            P.INFRA_READ,
            P.BOQ_READ,
            P.BOQ_EDIT,
            P.BOQ_ESTIMATE,
            P.BOQ_APPROVE_PRICING,
            P.BOQ_ISSUE,
            P.BOQ_ACCEPT,
            P.TEMPLATE_EDIT,
        }
    ),
    Role.SALES_MANAGER: frozenset(
        {
            *_READ_WORK,
            P.CUSTOMER_WRITE,
            P.PROJECT_WRITE,
            P.BRIEF_WRITE,
            P.GATE_SUBMIT,
            P.CUSTOMER_ACK_ISSUE,
            P.FILE_UPLOAD,
            P.PRISMSUITE_READ,
            P.PRISMSUITE_IMPORT,
            P.PRICE_READ,
            P.PRICE_WRITE,
            P.DATASET_READ,
            P.DATASET_WRITE,
            P.INFRA_READ,
            P.BOQ_READ,
            P.BOQ_EDIT,
            P.BOQ_ESTIMATE,
            P.BOQ_ISSUE,
            P.BOQ_ACCEPT,
        }
    ),
    Role.SOLUTION_ARCHITECT: frozenset(
        {
            P.ML_READ,
            P.REPORT_READ,
            P.PLAN_READ,
            P.PLAN_WRITE,
            *_READ_WORK,
            P.GATE_SUBMIT,
            P.GATE_APPROVE,
            P.CUSTOMER_ACK_ISSUE,
            P.FILE_UPLOAD,
            P.PRISMSUITE_READ,
            P.PRISMSUITE_IMPORT,
            P.PRISMSUITE_REVIEW,
            P.PRISMSUITE_APPROVE,
            P.CATALOGUE_WRITE,
            P.PRICE_READ,
            P.DATASET_READ,
            P.DATASET_WRITE,
            P.INFRA_READ,
            P.INFRA_WRITE,
            P.BOQ_READ,
            P.BOQ_EDIT,
            P.BOQ_ESTIMATE,
        }
    ),
    Role.AUDIT_ENGINEER: frozenset(
        {
            *_READ_WORK,
            P.GATE_SUBMIT,
            P.FILE_UPLOAD,
            P.PRISMSUITE_READ,
            P.PRISMSUITE_IMPORT,
            P.PRISMSUITE_REVIEW,
            P.BRIEF_WRITE,
            P.PRICE_READ,
            P.INFRA_READ,
            P.BOQ_ESTIMATE,
            P.DATASET_READ,
            P.DATASET_WRITE,
        }
    ),
    Role.TECHNICAL_LEAD: frozenset(
        {
            P.DASHBOARD_READ,
            P.REPORT_READ,
            P.FIELD_READ,
            P.FIELD_VERIFY,
            P.PLAN_READ,
            P.PLAN_WRITE,
            P.PLAN_BASELINE,
            P.TEMPLATE_EDIT,
            *_READ_WORK,
            P.GATE_SUBMIT,
            P.GATE_APPROVE,
            P.FILE_UPLOAD,
            P.PRISMSUITE_READ,
            P.PRISMSUITE_REVIEW,
            P.PRISMSUITE_APPROVE,
            P.DATASET_READ,
            P.INFRA_READ,
        }
    ),
    Role.PROJECT_MANAGER: frozenset(
        {
            P.DASHBOARD_READ,
            P.REPORT_READ,
            P.REPORT_WRITE,
            P.FIELD_READ,
            P.FIELD_MANAGE,
            P.PLAN_READ,
            P.PLAN_WRITE,
            P.PLAN_BASELINE,
            *_READ_WORK,
            P.PROJECT_WRITE,
            P.BRIEF_WRITE,
            P.PROJECT_MEMBERS,
            P.GATE_SUBMIT,
            P.GATE_APPROVE,
            P.CUSTOMER_ACK_ISSUE,
            P.FILE_UPLOAD,
            P.INFRA_READ,
        }
    ),
    Role.FIELD_ENGINEER: frozenset(
        {*_READ_WORK, P.FILE_UPLOAD, P.PLAN_READ, P.FIELD_READ, P.FIELD_WORK}
    ),
    Role.CUSTOMER_REP: frozenset({P.CUSTOMER_READ, P.PROJECT_READ, P.FILE_READ}),
}


def permissions_for(roles: set[Role] | frozenset[Role]) -> frozenset[P]:
    out: set[P] = set()
    for r in roles:
        out |= ROLE_PERMISSIONS[r]
    return frozenset(out)
