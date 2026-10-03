"""Field encryption with rotation (MultiFernet), plus per-subject keys for crypto-shredding.

Envelope scheme: every sensitive value is encrypted with a Fernet key from secrets
(P1_FERNET_KEYS, first key encrypts, all keys decrypt). Per-subject data keys (for personal
data in the audit log) are themselves stored encrypted with the master keys. Destroying a
subject key makes that person's audit payloads unreadable while the audit rows stay intact.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class DecryptionError(Exception):
    pass


@lru_cache
def _master() -> MultiFernet:
    keys = get_settings().fernet_key_list()
    if not keys:
        raise RuntimeError("P1_FERNET_KEYS is not configured")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def reset_key_cache() -> None:
    _master.cache_clear()


def encrypt(plaintext: bytes) -> bytes:
    return _master().encrypt(plaintext)


def decrypt(token: bytes) -> bytes:
    try:
        return _master().decrypt(token)
    except InvalidToken as exc:
        raise DecryptionError("cannot decrypt with the configured keys") from exc


def encrypt_str(value: str) -> str:
    return encrypt(value.encode()).decode()


def decrypt_str(token: str) -> str:
    return decrypt(token.encode()).decode()


def rotate(token: bytes) -> bytes:
    """Re-encrypt under the current primary key (used by the key rotation job)."""
    return _master().rotate(token)


def new_data_key() -> bytes:
    return Fernet.generate_key()


def wrap_data_key(data_key: bytes) -> bytes:
    return encrypt(data_key)


def unwrap_data_key(wrapped: bytes) -> bytes:
    return decrypt(wrapped)


def encrypt_with(data_key: bytes, plaintext: bytes) -> bytes:
    return Fernet(data_key).encrypt(plaintext)


def decrypt_with(data_key: bytes, token: bytes) -> bytes:
    try:
        return Fernet(data_key).decrypt(token)
    except InvalidToken as exc:
        raise DecryptionError("cannot decrypt with this data key") from exc
