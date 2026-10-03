"""The eight project stages, in order, and their default gate settings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.identity.contracts import Role


class Stage(StrEnum):
    AUDIT_INTAKE = "audit_intake"
    CURRENT_INFRA = "current_infra"
    IDEAL_INFRA = "ideal_infra"
    GAP_ANALYSIS = "gap_analysis"
    BOQ = "boq"
    IMPLEMENTATION_PLAN = "implementation_plan"
    FIELD_WORK = "field_work"
    COMPLETION = "completion"


STAGE_ORDER: list[Stage] = list(Stage)

STAGE_LABELS: dict[Stage, str] = {
    Stage.AUDIT_INTAKE: "Audit intake",
    Stage.CURRENT_INFRA: "Current IT infrastructure",
    Stage.IDEAL_INFRA: "Ideal IT infrastructure",
    Stage.GAP_ANALYSIS: "Gap analysis and recommendations",
    Stage.BOQ: "BOQ",
    Stage.IMPLEMENTATION_PLAN: "Implementation and configuration plan",
    Stage.FIELD_WORK: "Field work and verification",
    Stage.COMPLETION: "Completion report and certificate",
}


def next_stage(stage: Stage) -> Stage | None:
    i = STAGE_ORDER.index(stage)
    return STAGE_ORDER[i + 1] if i + 1 < len(STAGE_ORDER) else None


@dataclass(frozen=True)
class GateDefault:
    approver_roles: tuple[Role, ...]
    artifact_type: str
    requires_customer_ack: bool = False


# Every gate needs a locked artifact from the module that owns the stage. Approvers never
# include the role that normally does the work, and the service also blocks the submitter.
GATE_DEFAULTS: dict[Stage, GateDefault] = {
    Stage.AUDIT_INTAKE: GateDefault(
        (Role.SOLUTION_ARCHITECT, Role.TECHNICAL_LEAD), "prismsuite_audit"
    ),
    Stage.CURRENT_INFRA: GateDefault(
        (Role.SOLUTION_ARCHITECT, Role.TECHNICAL_LEAD), "infra_current"
    ),
    Stage.IDEAL_INFRA: GateDefault((Role.SOLUTION_ARCHITECT, Role.TECHNICAL_LEAD), "infra_ideal"),
    Stage.GAP_ANALYSIS: GateDefault((Role.SOLUTION_ARCHITECT, Role.DIRECTOR), "gap_register", True),
    Stage.BOQ: GateDefault((Role.SALES_HEAD, Role.DIRECTOR), "boq_version"),
    Stage.IMPLEMENTATION_PLAN: GateDefault(
        (Role.PROJECT_MANAGER, Role.TECHNICAL_LEAD), "implementation_plan"
    ),
    Stage.FIELD_WORK: GateDefault((Role.TECHNICAL_LEAD,), "field_work_summary"),
    Stage.COMPLETION: GateDefault((Role.DIRECTOR,), "completion_report", True),
}
