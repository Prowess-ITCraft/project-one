"""Reading configuration exports into flat key/value facts, per brand.

A parser recognises its brand's export and returns every key it can read; which keys prove which
target setting is data (`BrandFieldMap`), not code. That way the first real export from a site
can be inspected (`/verification/inspect`) and the mapping confirmed without a code change.

SonicWall (ADR 0019: first brand). Three shapes are read:
- the classic `.exp` settings file: base64 text of URL-encoded `key=value&key=value` pairs;
- plain text with `key=value` or `key: value` lines;
- JSON (for example from the SonicOS API), flattened to dotted keys.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import parse_qsl

MAX_EXPORT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ParsedExport:
    brand: str
    shape: str  # exp | text | json
    facts: dict[str, str] = field(default_factory=dict)


class ExportParser(Protocol):
    brand: str

    def parse(self, name: str, data: bytes) -> ParsedExport | None: ...


def _flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}.{i}"))
    elif obj is not None:
        out[prefix] = str(obj).strip()
    return out


_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-/]+)\s*[=:]\s*(.*?)\s*$")


def read_key_values(data: bytes) -> tuple[str, dict[str, str]] | None:
    """Any of the three shapes into (shape, facts). None when nothing readable is found."""
    if len(data) > MAX_EXPORT_BYTES:
        return None
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if text[:1] in "{[":
        try:
            return "json", _flatten(json.loads(text))
        except ValueError:
            pass
    compact = re.sub(r"\s+", "", text)
    if compact and re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        try:
            decoded = base64.b64decode(compact + "=" * (-len(compact) % 4), validate=False)
            inner = decoded.decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            inner = ""
        if "=" in inner and "&" in inner:
            pairs = parse_qsl(inner.strip("&"), keep_blank_values=True)
            if pairs:
                return "exp", {k.strip(): v.strip() for k, v in pairs if k.strip()}
    facts: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            facts[m.group(1)] = m.group(2).strip().strip('"')
    return ("text", facts) if facts else None


class SonicWallParser:
    brand = "sonicwall"
    _MARKERS = ("sonicwall", "sonicos", "sonic wall")

    def parse(self, name: str, data: bytes) -> ParsedExport | None:
        read = read_key_values(data)
        if read is None:
            return None
        shape, facts = read
        head = data[:4096].decode("utf-8", errors="replace")
        pairs = " ".join(f"{k} {v}" for k, v in list(facts.items())[:400])
        blob = f"{name} {head} {pairs}".lower()
        if not (name.lower().endswith(".exp") or any(m in blob for m in self._MARKERS)):
            return None
        return ParsedExport(self.brand, shape, facts)


PARSERS: list[ExportParser] = [SonicWallParser()]


def parse_export(name: str, data: bytes) -> ParsedExport | None:
    """The first parser that recognises the file, or None."""
    for p in PARSERS:
        got = p.parse(name, data)
        if got is not None:
            return got
    return None


# ------------------------------------------------------------------ rules

_TRUE = {"on", "1", "true", "yes", "enable", "enabled", "configured", "active"}
_FALSE = {"off", "0", "false", "no", "disable", "disabled", "none", "inactive"}


def _version(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:4])


def apply_rule(rule: dict[str, Any], value: str) -> tuple[str, str]:
    """Judge one exported value. Returns (outcome, reason). Ops: truthy, falsy, eq, ne, in,
    not_in, version_gte, record (show the value; a person judges it)."""
    op = str(rule.get("op", "record"))
    v = value.strip()
    low = v.lower()
    target = rule.get("value")
    if op == "truthy":
        ok = low in _TRUE
        return ("pass", "Turned on.") if ok else ("fail", f"Expected on, found {v or 'empty'}.")
    if op == "falsy":
        ok = low in _FALSE or low == ""
        return ("pass", "Turned off.") if ok else ("fail", f"Expected off, found {v}.")
    if op == "eq":
        ok = low == str(target).lower()
        return ("pass", "Matches.") if ok else ("fail", f"Expected {target}, found {v}.")
    if op == "ne":
        ok = low != str(target).lower()
        return ("pass", f"Not {target}.") if ok else ("fail", f"Still {v}.")
    if op in ("in", "not_in"):
        options = [str(x).lower() for x in (target or [])]
        ok = (low in options) == (op == "in")
        return ("pass", "Allowed value.") if ok else ("fail", f"{v} is not allowed.")
    if op == "version_gte":
        ok = _version(v) >= _version(str(target))
        return (
            ("pass", f"{v} is {target} or newer.")
            if ok
            else ("fail", f"{v} is older than {target}.")
        )
    return "not_checked", f"Read from the export: {v}. A person judges it."
