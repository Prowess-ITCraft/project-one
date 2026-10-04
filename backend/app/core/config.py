"""Application settings, loaded from the environment (and Docker secrets files)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="P1_",
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir="/run/secrets" if os.path.isdir("/run/secrets") else None,
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "Project One"
    api_prefix: str = "/api/v1"
    public_base_url: str = "http://localhost:9597"
    # The interactive API reference at /docs and the schema it reads. Set false to hide both.
    api_docs: bool = True

    # Database. The owner role runs migrations; the runtime role has no UPDATE/DELETE on audit_log.
    database_url: str = "postgresql+asyncpg://p1_app:p1_app_dev@localhost:9599/project_one"
    database_owner_url: str = (
        "postgresql+asyncpg://p1_owner:p1_owner_dev@localhost:9599/project_one"
    )
    db_runtime_role: str = "p1_app"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_statement_timeout_ms: int = 15000

    redis_url: str = "redis://localhost:9600/0"
    celery_broker_url: str = "redis://localhost:9600/1"

    s3_endpoint_url: str = "http://localhost:9601"
    s3_public_endpoint_url: str | None = None
    s3_access_key: SecretStr = SecretStr("p1minio")
    s3_secret_key: SecretStr = SecretStr("p1minio-dev-secret")
    s3_region: str = "us-east-1"
    s3_bucket_files: str = "p1-files"
    s3_bucket_backups: str = "p1-backups"
    s3_presign_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    # Email. An empty host means "not configured": messages are recorded as skipped, never lost.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "no-reply@itcraft.example"
    smtp_starttls: bool = True

    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 60.0

    # Security. Keys are comma separated lists. The first key signs or encrypts;
    # the others only verify or decrypt, which is how rotation works.
    jwt_signing_keys: SecretStr = SecretStr("dev-only-jwt-key-change-me-0123456789abcdef")
    jwt_issuer: str = "project-one"
    jwt_audience: str = "project-one-api"
    access_token_ttl_minutes: int = Field(default=15, ge=5, le=15)
    refresh_token_ttl_days: int = Field(default=14, ge=1, le=60)
    mfa_challenge_ttl_minutes: int = 5
    fernet_keys: SecretStr = SecretStr("")
    cors_allow_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:9595",
        "http://localhost:9597",
    ]
    cookie_secure: bool = True
    cookie_domain: str | None = None
    trusted_proxy_hops: int = 1

    login_max_failures: int = 5
    login_lockout_base_minutes: int = 15
    login_lockout_max_minutes: int = 1440

    rate_limit_default_per_minute: int = 300
    # Per address, on sign-in and MFA only. An office shares one address; guessing a password
    # is stopped by the per-account lockout (login_max_failures) instead.
    rate_limit_auth_per_minute: int = 60
    rate_limit_upload_per_minute: int = 20

    max_json_body_bytes: int = 1_048_576
    max_upload_bytes: int = 52_428_800

    backup_retention_days: int = 30

    # Document corpus (ADR 0014). 0 keeps original library files forever. A positive number
    # purges originals older than that many days, once their canonical JSON is verified.
    corpus_originals_retention_days: int = 0
    # A folder the worker watches for old BOQs and PrismSuite reports (every 5 minutes). Empty
    # turns the watch off. In compose it is ./inbox on the host, mounted at /data/inbox.
    library_inbox_dir: str = ""

    log_level: str = "INFO"
    log_json: bool = True
    otel_exporter_otlp_endpoint: str | None = None
    sentry_dsn: SecretStr | None = None

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    def jwt_keys(self) -> list[str]:
        return [k.strip() for k in self.jwt_signing_keys.get_secret_value().split(",") if k.strip()]

    def fernet_key_list(self) -> list[str]:
        return [k.strip() for k in self.fernet_keys.get_secret_value().split(",") if k.strip()]

    def validate_for_runtime(self) -> None:
        """Refuse to start in prod with dev secrets or missing keys."""
        problems: list[str] = []
        if not self.fernet_key_list():
            problems.append("P1_FERNET_KEYS is empty")
        if self.is_prod:
            if any(k.startswith("dev-only") for k in self.jwt_keys()):
                problems.append("P1_JWT_SIGNING_KEYS still uses the dev key")
            if any(len(k) < 32 for k in self.jwt_keys()):
                problems.append("JWT signing keys must be at least 32 characters")
            if not self.cookie_secure:
                problems.append("P1_COOKIE_SECURE must be true in prod")
            if not self.public_base_url.startswith("https://") or _local(self.public_base_url):
                problems.append(
                    "P1_PUBLIC_BASE_URL must be the https:// address people use (it goes into "
                    "links, emails and certificate QR codes)"
                )
            bad = [o for o in self.cors_allow_origins if not o.startswith("https://") or _local(o)]
            if not self.cors_allow_origins or bad:
                problems.append("P1_CORS_ALLOW_ORIGINS must list only https:// web addresses")
            if self.s3_public_endpoint_url and _local(self.s3_public_endpoint_url):
                problems.append(
                    "P1_S3_PUBLIC_ENDPOINT_URL points at this machine; leave it empty so files "
                    "are served through the app"
                )
            if self.s3_secret_key.get_secret_value() == "p1minio-dev-secret":
                problems.append("P1_S3_SECRET_KEY still uses the dev value")
            if not self.smtp_host:
                problems.append(
                    "P1_SMTP_HOST is empty: visit codes, waiver links and notices cannot be sent"
                )
        if problems:
            raise RuntimeError("Unsafe configuration: " + "; ".join(problems))


def _local(url: str) -> bool:
    return any(h in url for h in ("localhost", "127.0.0.1", "[::1]"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
