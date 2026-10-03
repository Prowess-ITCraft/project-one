"""Small, total value parsers. Each returns None for anything it cannot read; none of them raise."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from app.modules.prismsuite.snapshot import Score, Severity

NA = {"", "n/a", "na", "-", "--", "none", "nil", "not available", "null"}
_NUM = r"[-+]?\d+(?:[.,]\d+)?"
_SCORE_RE = re.compile(rf"(?P<v>{_NUM})\s*(?:%|/\s*(?P<of>{_NUM}))?")
_INT_RE = re.compile(r"[-+]?\d[\d,]*")
_DATE_RES = [
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"), "ymd"),
]
_REF_RE = re.compile(r"\bPS-(\d{2})(\d{2})(\d{4})-([A-Z0-9]{2,6})\b")
_CVSS_RE = re.compile(r"CVSS\s*(?:v?\d(?:\.\d)?)?\s*[:\-–]?\s*(\d{1,2}(?:\.\d)?)", re.I)
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)\b", re.I)


def clean(text: str | None) -> str:
    if text is None:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("▌", " ").replace(" ", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"[ \t\r\f\v]+", " ", t).strip()


def norm_key(text: str | None) -> str:
    """Lowercase, letters and digits only. Used to match headings and column names."""
    return re.sub(r"[^a-z0-9]+", " ", clean(text).lower()).strip()


def is_na(text: str | None) -> bool:
    return clean(text).lower().strip(" .") in NA


def text_or_none(text: str | None) -> str | None:
    return None if is_na(text) else clean(text)


def to_decimal(text: str) -> Decimal | None:
    try:
        d = Decimal(text.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def parse_int(text: str | None) -> int | None:
    if is_na(text):
        return None
    m = _INT_RE.search(clean(text))
    if not m:
        return None
    try:
        value = int(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return value if abs(value) < 10**9 else None


def parse_decimal(text: str | None) -> Decimal | None:
    if is_na(text):
        return None
    m = re.search(_NUM, clean(text))
    return to_decimal(m.group(0)) if m else None


def parse_score(text: str | None, *, default_out_of: Decimal = Decimal(100)) -> Score:
    """'58.7 / 100 (AT RISK)', '74.2 %', '50 / 100  (At Risk)', '3.83/10', 'N/A'."""
    raw = clean(text)
    if is_na(raw):
        return Score(value=None, out_of=default_out_of, raw=raw or None)
    m = _SCORE_RE.search(raw)
    if not m:
        return Score(value=None, out_of=default_out_of, raw=raw)
    value = to_decimal(m.group("v"))
    of = to_decimal(m.group("of")) if m.group("of") else default_out_of
    if value is None or of is None or of <= 0 or value < 0 or value > of:
        return Score(value=None, out_of=default_out_of, raw=raw)
    rest = raw[m.end() :].strip(" -()")
    label = re.sub(r"[()]", "", rest).strip(" -:") or None
    return Score(value=value, out_of=of, label=label[:80] if label else None, raw=raw)


def parse_date(text: str | None) -> date | None:
    raw = clean(text)
    for rx, order in _DATE_RES:
        m = rx.search(raw)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        y, mo, d = (c, b, a) if order == "dmy" else (a, b, c)
        try:
            return date(y, mo, d)
        except ValueError:
            continue
    return None


def parse_report_reference(text: str | None) -> tuple[str | None, date | None]:
    """'PS-10092026-SHA' -> ('PS-10092026-SHA', date(2026, 9, 10))."""
    m = _REF_RE.search(clean(text).upper())
    if not m:
        return None, None
    dd, mm, yyyy, _ = m.groups()
    try:
        d = date(int(yyyy), int(mm), int(dd))
    except ValueError:
        d = None
    return m.group(0), d


def parse_severity(text: str | None) -> tuple[Severity | None, Decimal | None]:
    raw = clean(text)
    sev = None
    low = raw.lower()
    for s in Severity:
        if s.value in low:
            sev = s
            break
    cvss = None
    if m := _CVSS_RE.search(raw):
        cvss = to_decimal(m.group(1))
        if cvss is not None and not (Decimal(0) <= cvss <= Decimal(10)):
            cvss = None
    return sev, cvss


def find_cve(text: str | None) -> str | None:
    m = _CVE_RE.search(clean(text))
    return m.group(0).upper() if m else None


def size_in_gb(text: str | None) -> Decimal | None:
    m = _GB_RE.search(clean(text))
    if not m:
        return None
    value = to_decimal(m.group(1))
    if value is None:
        return None
    unit = m.group(2).upper()
    return value * {"TB": Decimal(1024), "GB": Decimal(1), "MB": Decimal(1) / Decimal(1024)}[unit]


def split_list(text: str | None, *, commas: bool = False) -> list[str]:
    """Cell text with one item per line (and optionally comma separated items)."""
    raw = (text or "").replace("\r", "\n")
    pattern = r"\n|,(?!\d)" if commas else r"\n"
    parts = re.split(pattern, raw)
    return [p for p in (clean(x).strip("•● ") for x in parts) if p and not is_na(p)]
