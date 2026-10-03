"""Virus scanning behind an interface. Production uses clamd over TCP (INSTREAM)."""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings
from app.core.resilience import CircuitBreaker, call_with_retry

CHUNK = 64 * 1024


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None
    engine: str


class VirusScanner(Protocol):
    async def scan(self, data: bytes) -> ScanResult: ...


class ClamdScanner:
    """Streams bytes to clamd's INSTREAM command. Fails closed: no scan, no upload."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.breaker = CircuitBreaker("Virus scanner", threshold=3, reset_after=30)

    async def _scan_once(self, data: bytes) -> ScanResult:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(b"zINSTREAM\0")
            for i in range(0, len(data), CHUNK):
                chunk = data[i : i + CHUNK]
                writer.write(struct.pack("!L", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack("!L", 0))
            await writer.drain()
            reply = (await reader.read(4096)).rstrip(b"\0").decode("utf-8", "replace").strip()
        finally:
            writer.close()
            await writer.wait_closed()
        # "stream: OK" or "stream: Eicar-Signature FOUND" or "INSTREAM size limit exceeded. ERROR"
        if reply.endswith("OK"):
            return ScanResult(clean=True, signature=None, engine="clamav")
        if reply.endswith("FOUND"):
            sig = reply.split(":", 1)[-1].removesuffix("FOUND").strip()
            return ScanResult(clean=False, signature=sig, engine="clamav")
        raise OSError(f"clamd error: {reply[:200]}")

    async def scan(self, data: bytes) -> ScanResult:
        return await call_with_retry(
            lambda: self._scan_once(data), breaker=self.breaker, attempts=2, timeout=self.timeout
        )


_scanner: VirusScanner | None = None


def get_scanner() -> VirusScanner:
    global _scanner
    if _scanner is None:
        s = get_settings()
        _scanner = ClamdScanner(s.clamav_host, s.clamav_port, s.clamav_timeout_seconds)
    return _scanner


def set_scanner(scanner: VirusScanner | None) -> None:
    """Swap the scanner (tests use a local EICAR detector; later phases may add others)."""
    global _scanner
    _scanner = scanner
