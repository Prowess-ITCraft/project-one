"""Adapter for a structured PrismSuite export (JSON in the AuditSnapshot shape).

When PrismSuite can export JSON, this is all that is needed: no Word parsing, no guessing.
The contract is the snapshot schema in `snapshot.py` (`schema_version` 1.x). A field the export
leaves out is reported as missing, exactly as with the Word reader.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.modules.prismsuite.parsers.base import ParseFailure, ParseResult, register
from app.modules.prismsuite.snapshot import (
    SCHEMA_VERSION,
    AuditSnapshot,
    FieldReport,
    FieldStatus,
    ReadReport,
)

PARSER_NAME = "prismsuite.json.v1"
REQUIRED = {
    "/header/customer_name": "customer name",
    "/header/report_reference": "report reference",
    "/header/audit_date": "audit date",
    "/scores/security/value": "security score",
    "/scores/high_availability/value": "high availability score",
}


def _get(doc: dict[str, Any], pointer: str) -> Any:
    node: Any = doc
    for part in pointer.strip("/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class PrismSuiteJsonParserV1:
    name = PARSER_NAME
    kinds = frozenset({"json"})

    def detect(self, data: bytes) -> float:
        try:
            doc = json.loads(data[:2_000_000])
        except (ValueError, UnicodeDecodeError):
            return 0.0
        if not isinstance(doc, dict):
            return 0.0
        score = 0.0
        if str(doc.get("schema_version", "")).startswith(SCHEMA_VERSION.split(".")[0] + "."):
            score += 0.5
        if isinstance(doc.get("header"), dict):
            score += 0.3
        if isinstance(doc.get("scores"), dict):
            score += 0.2
        return min(score, 1.0)

    def parse(self, data: bytes) -> ParseResult:
        try:
            doc = json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ParseFailure("The file is not valid JSON.") from exc
        if not isinstance(doc, dict):
            raise ParseFailure("The JSON must be an object.")
        try:
            snapshot = AuditSnapshot.model_validate(doc)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = "/".join(str(x) for x in first["loc"])
            raise ParseFailure(
                f"The JSON does not match the snapshot schema at {where}: {first['msg']}"
            ) from exc
        report = ReadReport(parser=PARSER_NAME)
        for pointer, label in REQUIRED.items():
            value = _get(doc, pointer)
            if value is None:
                report.fields.append(
                    FieldReport(
                        path=pointer,
                        status=FieldStatus.MISSING,
                        message=f"The export has no {label}.",
                        required=True,
                    )
                )
            else:
                report.fields.append(
                    FieldReport(
                        path=pointer, status=FieldStatus.OK, source="JSON export", required=True
                    )
                )
        return ParseResult(snapshot=snapshot, report=report)


register(PrismSuiteJsonParserV1())
