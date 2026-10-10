"""The list of installed modules: their routers, outbox handlers and models.

Adding a module means adding it here. Nothing else outside the module changes.
"""

from __future__ import annotations

import importlib

from fastapi import APIRouter

# Import order matters only for model registration with SQLAlchemy metadata.
MODULES = [
    "audit_log",
    "identity",
    "customers",
    "files",
    "prismsuite",
    "catalogue",
    "datasets",
    "infra",
    "boq",
    "planning",
    "notifications",
    "fieldops",
    "verification",
    "reporting",
    "ml",
    "search",
]

_HANDLER_MODULES = [
    "app.modules.customers.handlers",
    "app.modules.catalogue.handlers",
    "app.modules.prismsuite.handlers",
    "app.modules.datasets.handlers",
    "app.modules.verification.handlers",
    "app.modules.ml.handlers",
    "app.modules.search.handlers",
]


def load_models() -> None:
    import app.core.flags
    import app.core.idempotency
    import app.core.outbox
    import app.core.sequences  # noqa: F401

    for m in MODULES:
        try:
            importlib.import_module(f"app.modules.{m}.models")
        except ModuleNotFoundError as exc:
            if exc.name != f"app.modules.{m}.models":
                raise


def load_handlers() -> None:
    from app.core.events import mark_handlers_loaded

    for path in _HANDLER_MODULES:
        try:
            importlib.import_module(path)
        except ModuleNotFoundError as exc:
            if exc.name != path:
                raise
    mark_handlers_loaded()


def routers() -> list[APIRouter]:
    from app.modules.audit_log.api import router as audit_router
    from app.modules.customers import api as customers_api
    from app.modules.identity import api as identity_api

    out: list[APIRouter] = [
        identity_api.auth_router,
        identity_api.account_router,
        identity_api.users_router,
        identity_api.roles_router,
        identity_api.admin_router,
        audit_router,
        customers_api.customers_router,
        customers_api.projects_router,
        customers_api.gates_router,
        customers_api.insights_router,
        customers_api.public_router,
    ]
    for optional in (
        "files",
        "prismsuite",
        "catalogue",
        "datasets",
        "infra",
        "boq",
        "planning",
        "notifications",
        "fieldops",
        "verification",
        "reporting",
        "ml",
        "search",
    ):
        try:
            mod = importlib.import_module(f"app.modules.{optional}.api")
        except ModuleNotFoundError as exc:
            if exc.name != f"app.modules.{optional}.api":
                raise
            continue
        out.extend(mod.routers)
    return out
