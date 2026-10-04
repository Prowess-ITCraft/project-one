"""Production refuses to start with settings that would break sign-in, links or email."""

from typing import Any

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings

GOOD: dict[str, Any] = {
    "env": "prod",
    "public_base_url": "https://p1.itcraft.net.in",
    "cors_allow_origins": ["https://p1.itcraft.net.in"],
    "cookie_secure": True,
    "jwt_signing_keys": "k" * 48,
    "fernet_keys": Fernet.generate_key().decode(),
    "s3_secret_key": "a-real-storage-secret-0123456789",
    "smtp_host": "smtp.example.net",
}


def test_good_production_settings_start() -> None:
    Settings(**GOOD).validate_for_runtime()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"public_base_url": "http://p1.itcraft.net.in"}, "P1_PUBLIC_BASE_URL"),
        ({"public_base_url": "https://localhost:9597"}, "P1_PUBLIC_BASE_URL"),
        ({"cors_allow_origins": ["http://localhost:9595"]}, "P1_CORS_ALLOW_ORIGINS"),
        ({"cors_allow_origins": []}, "P1_CORS_ALLOW_ORIGINS"),
        ({"s3_secret_key": "p1minio-dev-secret"}, "P1_S3_SECRET_KEY"),
        ({"smtp_host": ""}, "P1_SMTP_HOST"),
        ({"cookie_secure": False}, "P1_COOKIE_SECURE"),
        ({"jwt_signing_keys": "short"}, "at least 32"),
    ],
)
def test_unsafe_production_settings_are_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        Settings(**{**GOOD, **change}).validate_for_runtime()


def test_development_is_not_held_to_production_rules() -> None:
    Settings(
        **{**GOOD, "env": "dev", "public_base_url": "http://localhost:9597", "smtp_host": ""}
    ).validate_for_runtime()
