"""The document corpus: every library file converted once into a compact canonical JSON record
(ADR 0014). `build_record` is pure and needs no database, so the same code runs in the worker,
in tests and in `cli corpus convert` on a laptop.

Record schema `p1.corpus.v1`:

    schema, cleaning_version, built_at
    source    name, sha256, bytes, media_type, file_kind, pages, origin
    kind      boq | audit | other
    parser    name, detect_score
    document  BOQ facts (doc_kind, quote_ref, quote_date, customer, validity_days, gst_rate)
              or audit header facts
    lines     cleaned BOQ lines with labels (BOQ only)
    audit     the audit snapshot, and `facts` the flattened facts (audit only)
    text      pages (plain text) and chars
    quality   score 0 to 100, parts, issues
    sizes     original bytes, json bytes, gzip bytes

Money is written as strings ("1562.00") so no precision is lost.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.core.timeutil import utcnow
from app.modules.datasets import cleaning, quality
from app.modules.datasets.extract import MEDIA_TYPES, Extracted, extract
from app.modules.datasets.importers import audit as audit_rows
from app.modules.datasets.importers import boq

SCHEMA = "p1.corpus.v1"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
BOQ_DETECT_FLOOR = 0.5
_KNOWN_HEADINGS = ["High Priority", "To Consider", "Optional", "Options"]


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_jsonable(x) for x in v]
    return v


@dataclass(frozen=True)
class BuiltRecord:
    record: dict[str, Any]
    gz: bytes  # the gzipped JSON, ready to store

    @property
    def kind(self) -> str:
        return str(self.record["kind"])

    @property
    def score(self) -> int:
        return int(self.record["quality"]["score"])


def clean_boq_lines(doc: boq.BoqDocument) -> list[dict[str, Any]]:
    """Clean and label every line of a parsed BOQ. Lines are never dropped: a line that cannot be
    repaired keeps its low confidence and its issues, and goes to review."""
    headings = list(
        {
            *_KNOWN_HEADINGS,
            *(ln.priority_group for ln in doc.lines),
            *(ln.section for ln in doc.lines),
        }
    )
    out: list[dict[str, Any]] = []
    for ln in doc.lines:
        raw = cleaning.normalise_text(ln.component)
        repaired, heading = cleaning.repair_interleaved(raw, headings)
        component = cleaning.fix_spelling(repaired)
        issues = list(ln.issues)
        conf = ln.confidence
        flags: list[str] = []
        if heading:
            flags.append("repaired_interleaved_heading")
            issues = [i for i in issues if "garbled" not in i] + [
                f"The heading '{heading}' was printed over this line and was taken out. Check the text."
            ]
            # Repaired text is a strong suggestion, not a fact: it stays below the review floor
            # so a person confirms it (RULES.md, data rule 4).
            conf = max(conf, 0.75)
        if component != raw:
            flags.append("text_cleaned")
        description = cleaning.fix_spelling(cleaning.normalise_text(ln.description))
        inclusions = [cleaning.fix_spelling(cleaning.normalise_text(i)) for i in ln.inclusions]
        out.append(
            {
                "line_ref": ln.line_ref,
                "option": ln.option or None,
                "priority_group": cleaning.normalise_text(ln.priority_group) or None,
                "section": cleaning.normalise_text(ln.section) or None,
                "component": component,
                "component_raw": ln.component if ln.component != component else None,
                "canonical": cleaning.canonical_name(component),
                "name_key": cleaning.name_key(component),
                "description": description or None,
                "inclusions": [i for i in inclusions if i],
                "qty": ln.qty,
                "unit_price": ln.unit_price,
                "amount": ln.amount,
                "confidence": round(conf, 3),
                "issues": issues,
                "flags": flags,
            }
        )
    labels = cleaning.label_lines(
        [(o["section"] or "", o["component"], o["description"] or "", o["inclusions"]) for o in out]
    )
    for o, lab in zip(out, labels, strict=True):
        o["label"] = {
            "gap_type": lab.gap_type,
            "line_role": lab.line_role,
            "rule": lab.rule,
            "confidence": lab.confidence,
        }
    return out


def _boq_part(data: bytes, ex: Extracted) -> dict[str, Any] | None:
    score = boq.detect_pdf(data) if ex.file_kind == "pdf" else boq.detect_xlsx(data)
    if score < BOQ_DETECT_FLOOR:
        return None
    doc = boq.parse_pdf(data) if ex.file_kind == "pdf" else boq.parse_xlsx(data)
    lines = clean_boq_lines(doc)
    facts = {
        "doc_kind": doc.kind,
        "quote_ref": doc.quote_ref,
        "quote_date": doc.quote_date,
        "customer": cleaning.normalise_text(doc.customer) or None,
        "validity_days": doc.validity_days,
        "gst_rate": doc.gst_rate,
        "warnings": doc.warnings,
    }
    return {
        "kind": "boq",
        "parser": {"name": f"boq.{ex.file_kind}.v1", "detect_score": round(score, 3)},
        "document": facts,
        "lines": lines,
        "quality": quality.boq_quality(facts, lines),
    }


def _audit_part(data: bytes, ex: Extracted) -> dict[str, Any] | None:
    from app.modules.prismsuite.contracts import parse_report

    parsed = parse_report(data, ex.file_kind)
    if parsed is None:
        return None
    facts = audit_rows.flatten(parsed.snapshot)
    h = parsed.snapshot.header
    return {
        "kind": "audit",
        "parser": {"name": parsed.parser_name, "detect_score": 1.0},
        "document": {
            "report_ref": h.report_reference,
            "customer": h.customer_name,
            "audit_date": h.audit_date,
            "unread_fields": parsed.blocking,
            "conflicts": parsed.conflicts,
            "counts": parsed.counts,
        },
        "audit": parsed.snapshot.model_dump(mode="json"),
        "facts": facts,
        "quality": quality.audit_quality(parsed.blocking, parsed.conflicts, len(facts)),
    }


def build_record(
    data: bytes, name: str, *, origin: str = "upload", built_at: datetime | None = None
) -> BuiltRecord:
    """Convert one file into its canonical record. Raises the parser's error when a file is
    recognised but unreadable; an unrecognised file becomes kind `other` with its text kept."""
    ex = extract(data)
    part: dict[str, Any] | None = None
    if ex.file_kind in ("pdf", "xlsx"):
        part = _boq_part(data, ex)
    elif ex.file_kind in ("docx", "json"):
        part = _audit_part(data, ex)
    if part is None:
        part = {
            "kind": "other",
            "parser": {"name": None, "detect_score": 0.0},
            "document": {},
            "quality": {
                "score": 0,
                "parts": {},
                "issues": ["Not a BOQ or a PrismSuite report. The text is kept for search."],
            },
        }
    pages = [cleaning.normalise_text(p) for p in ex.pages]
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "cleaning_version": cleaning.CLEANING_VERSION,
        "built_at": (built_at or utcnow()).isoformat(),
        "source": {
            "name": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "media_type": MEDIA_TYPES[ex.file_kind],
            "file_kind": ex.file_kind,
            "pages": len(ex.pages),
            "origin": origin,
        },
        **part,
        "text": {"pages": pages, "chars": sum(len(p) for p in pages)},
    }
    record = _jsonable(record)
    body = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    gz = gzip.compress(body, compresslevel=9, mtime=0)
    record["sizes"] = {"original": len(data), "json": len(body), "gzip": len(gz)}
    gz = gzip.compress(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(),
        compresslevel=9,
        mtime=0,
    )
    return BuiltRecord(record, gz)


def read_gz(gz: bytes) -> dict[str, Any]:
    return dict(json.loads(gzip.decompress(gz)))


def collection_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows a record adds to the historical BOQ collection (money back to Decimal)."""
    if record.get("kind") != "boq":
        return []
    doc = record["document"]
    src = record["source"]
    qd = doc.get("quote_date")
    out = []
    for ln in record["lines"]:
        out.append(
            {
                "source_sha256": src["sha256"],
                "source_name": src["name"],
                "doc_kind": doc.get("doc_kind"),
                "quote_ref": doc.get("quote_ref"),
                "quote_date": date.fromisoformat(qd) if qd else None,
                "customer": doc.get("customer"),
                "validity_days": doc.get("validity_days"),
                "gst_rate": Decimal(doc["gst_rate"]) if doc.get("gst_rate") else None,
                "priority_group": ln.get("priority_group"),
                "section": ln.get("section"),
                "line_ref": ln["line_ref"],
                "option": ln.get("option"),
                "component": ln["component"],
                "description": ln.get("description"),
                "inclusions": "\n".join(ln.get("inclusions") or []) or None,
                "qty": ln.get("qty"),
                "unit_price": Decimal(ln["unit_price"]) if ln.get("unit_price") else None,
                "amount": Decimal(ln["amount"]) if ln.get("amount") else None,
                "confidence": ln.get("confidence"),
                "gap_type": ln["label"]["gap_type"],
                "line_role": ln["label"]["line_role"],
                "label_rule": ln["label"]["rule"],
                "name_key": ln.get("name_key"),
                "cleaning_version": record.get("cleaning_version"),
            }
        )
    return out
