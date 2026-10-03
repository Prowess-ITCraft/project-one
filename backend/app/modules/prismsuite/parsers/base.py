"""Parser interface and registry. A new PrismSuite layout is a new class plus one `register()`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.prismsuite.snapshot import AuditSnapshot, ReadReport


@dataclass(frozen=True)
class ParseResult:
    snapshot: AuditSnapshot
    report: ReadReport


class ParseFailure(Exception):
    """The input is not something this parser can read at all (wrong format, corrupt file)."""


class AuditParser(Protocol):
    name: str  # stable id stored with every import, e.g. "prismsuite.docx.v1"
    kinds: frozenset[str]  # file kinds from the files module, e.g. {"docx"}

    def detect(self, data: bytes) -> float:
        """Confidence 0..1 that this parser fits the input. Must never raise."""
        ...

    def parse(self, data: bytes) -> ParseResult:
        """Parse. Raise ParseFailure only when nothing can be read; otherwise report per field."""
        ...


_registry: dict[str, AuditParser] = {}


def register(parser: AuditParser) -> AuditParser:
    if parser.name in _registry and _registry[parser.name] is not parser:
        raise RuntimeError(f"parser {parser.name} registered twice")
    _registry[parser.name] = parser
    return parser


def get(name: str) -> AuditParser | None:
    return _registry.get(name)


def all_parsers() -> list[AuditParser]:
    return list(_registry.values())


def pick(data: bytes, kind: str, preferred: str | None = None) -> AuditParser | None:
    if preferred:
        p = _registry.get(preferred)
        return p if p and kind in p.kinds else None
    best: tuple[float, AuditParser] | None = None
    for p in _registry.values():
        if kind not in p.kinds:
            continue
        score = p.detect(data)
        if score > 0 and (best is None or score > best[0]):
            best = (score, p)
    return best[1] if best and best[0] >= 0.5 else None
