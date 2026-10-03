from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.errors import Forbidden
from app.modules.identity.permissions import P, Role


@dataclass(frozen=True)
class Principal:
    """The signed-in person for this request."""

    user_id: uuid.UUID
    email: str
    full_name: str
    initials: str
    roles: frozenset[Role]
    permissions: frozenset[P]
    session_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    via_cookie: bool = False
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def has(self, perm: P) -> bool:
        return perm in self.permissions

    def has_role(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)

    @property
    def is_customer(self) -> bool:
        return Role.CUSTOMER_REP in self.roles

    def require(self, perm: P) -> None:
        if perm not in self.permissions:
            raise Forbidden()

    @property
    def label(self) -> str:
        return f"{self.full_name} <{self.email}>"


SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def system_principal(name: str = "system", permissions: frozenset[P] = frozenset()) -> Principal:
    """The identity background jobs act as (for example the library folder watcher). It holds
    only the permissions the job needs and appears in the audit log as `system:<name>`."""
    return Principal(
        user_id=SYSTEM_USER_ID,
        email=f"{name}@system.local",
        full_name=f"system:{name}",
        initials="SYS",
        roles=frozenset(),
        permissions=permissions,
        session_id=SYSTEM_USER_ID,
    )


def ensure_different_people(doer_id: uuid.UUID | None, verifier_id: uuid.UUID, what: str) -> None:
    """Segregation of duties: the person who did the work can never verify or approve it."""
    if doer_id is not None and doer_id == verifier_id:
        raise Forbidden(
            f"You did this {what} yourself, so someone else must verify or approve it.",
            code="segregation_of_duties",
        )
