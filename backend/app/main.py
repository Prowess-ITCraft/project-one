"""FastAPI application factory. Composes core middleware with every module's routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers
from app.core.health import router as health_router
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.redis import close_redis
from app.modules import registry

log = structlog.get_logger(__name__)


def _init_observability(app: FastAPI) -> None:
    s = get_settings()
    if s.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=s.sentry_dsn.get_secret_value(),
            environment=s.env,
            send_default_pii=False,
            traces_sample_rate=0.05,
        )
    if s.otel_exporter_otlp_endpoint:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from app.core.db import get_engine

        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": "project-one-api", "deployment.environment": s.env}
            )
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{s.otel_exporter_otlp_endpoint}/v1/traces")
            )
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
        SQLAlchemyInstrumentor().instrument(engine=get_engine().sync_engine)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_settings().validate_for_runtime()
    registry.load_handlers()
    log.info("startup", env=get_settings().env)
    yield
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    configure_logging()
    s = get_settings()
    app = FastAPI(
        title="Project One API",
        version="0.3.0",
        description="PrismSuite audit to certified implementation. ITCraft / IITPL.",
        openapi_url=f"{s.api_prefix}/openapi.json" if s.api_docs else None,
        docs_url="/docs" if s.api_docs else None,
        redoc_url=None,
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": False},
    )
    install_error_handlers(app)
    # Outermost first: request context wraps everything so every response carries a request id.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-CSRF-Token",
            "X-Auth-Mode",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID", "Retry-After", "Idempotent-Replayed"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    from app import ops
    from app.core.health import EXTRA_METRICS

    if ops.ops_metrics not in EXTRA_METRICS:
        EXTRA_METRICS.append(ops.ops_metrics)
    for router in registry.routers():
        app.include_router(router, prefix=s.api_prefix)
    _init_observability(app)
    return app


app = create_app()
