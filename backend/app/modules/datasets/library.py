"""The library: drop old BOQs and PrismSuite reports in, and the engine reads them and grows two
built-in datasets (historical BOQ lines and audit findings).

- A file arrives by upload or from a watched folder.
- Its hash is checked, so the same file never adds rows twice.
- It is read with the right importer. Rows the reader is sure about are appended as a new
  version of the collection; uncertain rows are held in the quarantine for a person to fix.
- Every step is recorded, and the dataset lineage names the source file.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import outbox
from app.core.errors import ValidationFailed
from app.core.events import DomainEvent
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import AuditContext, record
from app.modules.datasets import corpus, corpus_store, service
from app.modules.datasets.engine import frame
from app.modules.datasets.importers import boq
from app.modules.datasets.models import (
    COLLECTION_AUDIT,
    COLLECTION_BOQ,
    SYSTEM_USER,
    CorpusDocument,
    Dataset,
    DatasetShare,
    LibraryFile,
    QuarantineRow,
)
from app.modules.files.contracts import read_file_system, store_upload
from app.modules.identity.contracts import P, Principal, audit_context, system_principal
from app.modules.prismsuite.contracts import ReportUnreadable

log = structlog.get_logger(__name__)

LIBRARY_ADDED = "datasets.library_file_added"
LIBRARY_PROCESSED = "datasets.library_file_processed"
CONFIDENCE_FLOOR = 0.8
SUFFIXES = {".pdf", ".xlsx", ".docx", ".json"}
VIEW_ROLES = [
    "admin",
    "director",
    "sales_head",
    "sales_manager",
    "solution_architect",
    "audit_engineer",
    "technical_lead",
]

D = pa.decimal128(14, 2)
BOQ_SCHEMA = pa.schema(
    [
        ("source_sha256", pa.string()),
        ("source_name", pa.string()),
        ("doc_kind", pa.string()),
        ("quote_ref", pa.string()),
        ("quote_date", pa.date32()),
        ("customer", pa.string()),
        ("validity_days", pa.int64()),
        ("gst_rate", D),
        ("priority_group", pa.string()),
        ("section", pa.string()),
        ("line_ref", pa.string()),
        ("option", pa.string()),
        ("component", pa.string()),
        ("description", pa.string()),
        ("inclusions", pa.string()),
        ("qty", pa.int64()),
        ("unit_price", D),
        ("amount", D),
        ("confidence", pa.float64()),
        # Added with the corpus (ADR 0014): cleaned labels, so history is ready for training.
        ("gap_type", pa.string()),
        ("line_role", pa.string()),
        ("label_rule", pa.string()),
        ("name_key", pa.string()),
        ("cleaning_version", pa.string()),
    ]
)
AUDIT_SCHEMA = pa.schema(
    [
        ("source_sha256", pa.string()),
        ("source_name", pa.string()),
        ("report_ref", pa.string()),
        ("customer", pa.string()),
        ("audit_date", pa.date32()),
        ("category", pa.string()),
        ("key", pa.string()),
        ("value_num", D),
        ("value_text", pa.string()),
        ("out_of", D),
        ("managed", pa.bool_()),
        ("used_percent", D),
        ("severity", pa.string()),
    ]
)
SCHEMAS = {COLLECTION_BOQ: BOQ_SCHEMA, COLLECTION_AUDIT: AUDIT_SCHEMA}
TITLES = {
    COLLECTION_BOQ: (
        "Historical BOQ lines",
        "Every line of every past BOQ and quotation added to the library.",
    ),
    COLLECTION_AUDIT: (
        "Audit findings",
        "Scores, counts, upgrade needs, vulnerabilities and recommendations from every PrismSuite report added to the library.",
    ),
}


def _system() -> Principal:
    return system_principal(
        "library",
        frozenset({P.FILE_UPLOAD, P.FILE_READ, P.DATASET_READ, P.DATASET_WRITE, P.DATASET_ADMIN}),
    )


async def ensure_collection(session: AsyncSession, key: str) -> Dataset:
    ds = await session.scalar(
        select(Dataset).where(Dataset.collection_key == key, Dataset.deleted_at.is_(None))
    )
    if ds is not None:
        return ds
    name, desc = TITLES[key]
    ds = Dataset(
        name=name, description=desc, tags=["library"], collection_key=key, owner_id=SYSTEM_USER
    )
    session.add(ds)
    await session.flush()
    for role in VIEW_ROLES:
        session.add(
            DatasetShare(
                dataset_id=ds.id, kind="role", principal=role, access="view", granted_by=SYSTEM_USER
            )
        )
    await session.flush()
    empty = SCHEMAS[key].empty_table()
    await service.write_version(
        session,
        ds,
        empty,
        step={"op": "create_collection"},
        summary="Empty collection",
        actor_id=SYSTEM_USER,
        parent=None,
    )
    return ds


def _table(schema: pa.Schema, rows: list[dict[str, Any]]) -> pa.Table:
    cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
    return pa.table({n: pa.array(v, type=schema.field(n).type) for n, v in cols.items()})


def _evolve(current: pa.Table, schema: pa.Schema) -> pa.Table:
    """Bring an older collection version up to the current schema: columns added since are
    filled with nulls, so old rows and new rows live in one table."""
    for f in schema:
        if f.name not in current.column_names:
            current = current.append_column(f, pa.nulls(current.num_rows, type=f.type))
    return current.select(schema.names).cast(schema)


async def _append(session: AsyncSession, key: str, new: pa.Table, lf: LibraryFile) -> int:
    if new.num_rows == 0:
        return 0
    ds = await ensure_collection(session, key)
    latest = await service.get_version(session, ds)
    current = _evolve(await service.load_table(latest), SCHEMAS[key])
    merged = pa.concat_tables([current, new.cast(SCHEMAS[key])])
    await service.write_version(
        session,
        ds,
        merged,
        step={
            "op": "library_ingest",
            "file": lf.original_name,
            "sha256": lf.sha256,
            "rows": new.num_rows,
        },
        summary=f"Added {lf.original_name}",
        actor_id=lf.uploaded_by,
        parent=latest,
    )
    return int(new.num_rows)


def _coerce(schema: pa.Schema, row: dict[str, Any]) -> dict[str, Any]:
    """Corpus records keep money and dates as strings; the collection wants typed values."""
    out: dict[str, Any] = {}
    for f in schema:
        v = row.get(f.name)
        if isinstance(v, str):
            if pa.types.is_decimal(f.type):
                v = Decimal(v)
            elif pa.types.is_date(f.type):
                v = date.fromisoformat(v[:10])
        out[f.name] = v
    return out


# ------------------------------------------------------------------ entry points


async def register(
    session: AsyncSession,
    *,
    file_id: uuid.UUID | None,
    name: str,
    sha256: str,
    source: str,
    uploaded_by: uuid.UUID,
) -> tuple[LibraryFile, bool]:
    """Record a file in the library. Returns (record, is_new). A known hash is not added twice."""
    existing = await session.scalar(select(LibraryFile).where(LibraryFile.sha256 == sha256))
    if existing is not None:
        return existing, False
    lf = LibraryFile(
        file_id=file_id, original_name=name, sha256=sha256, source=source, uploaded_by=uploaded_by
    )
    session.add(lf)
    await session.flush()
    outbox.publish(
        session,
        DomainEvent(
            event_type=LIBRARY_ADDED,
            aggregate_type="library_file",
            aggregate_id=str(lf.id),
            actor_id=uploaded_by,
            payload={"library_file_id": str(lf.id)},
        ),
    )
    return lf, True


async def upload(
    session: AsyncSession,
    principal: Principal,
    *,
    data: bytes,
    filename: str,
    client_ip: str | None,
) -> tuple[LibraryFile, bool]:
    principal.require(P.DATASET_WRITE)
    ref = await store_upload(
        session,
        principal,
        data=data,
        filename=filename,
        purpose="library",
        project_id=None,
        client_ip=client_ip,
    )
    lf, new = await register(
        session,
        file_id=ref.id,
        name=ref.original_name,
        sha256=ref.sha256,
        source="upload",
        uploaded_by=principal.user_id,
    )
    await record(
        session,
        audit_context(principal),
        action="library_upload",
        entity_type="library_file",
        entity_id=lf.id,
        after={"name": ref.original_name, "new": new},
        only_changes=False,
    )
    await session.commit()
    return lf, new


async def process(session: AsyncSession, library_file_id: uuid.UUID) -> LibraryFile:
    """Read one queued file and grow the matching collection. Safe to run twice."""
    lf = await session.get(LibraryFile, library_file_id, with_for_update=True)
    if lf is None:
        raise ValueError(f"unknown library file {library_file_id}")
    if lf.status != "queued":
        return lf
    if lf.file_id is None:
        lf.status, lf.message = "failed", "The stored file is missing."
        await session.commit()
        return lf
    ref, data = await read_file_system(session, lf.file_id)
    lf.processed_at = utcnow()
    try:
        await _read_and_append(session, lf, ref.kind, data)
    except (boq.BoqParseError, ReportUnreadable) as exc:
        lf.status, lf.message, lf.kind = "failed", str(exc)[:500], lf.kind or "unknown"
    except ValidationFailed as exc:
        lf.status, lf.message = "failed", str(exc)[:500]
    outbox.publish(
        session,
        DomainEvent(
            event_type=LIBRARY_PROCESSED,
            aggregate_type="library_file",
            aggregate_id=str(lf.id),
            actor_id=lf.uploaded_by,
            payload={
                "library_file_id": str(lf.id),
                "status": lf.status,
                "kind": lf.kind,
                "rows_added": lf.rows_added,
                "rows_held": lf.rows_held,
            },
        ),
    )
    await record(
        session,
        AuditContext.system("library"),
        action="library_process",
        entity_type="library_file",
        entity_id=lf.id,
        after={
            "status": lf.status,
            "kind": lf.kind,
            "rows_added": lf.rows_added,
            "rows_held": lf.rows_held,
            "parser": lf.parser,
        },
        only_changes=False,
    )
    await session.commit()
    return lf


async def save_corpus(
    session: AsyncSession, built: corpus.BuiltRecord, *, library_file_id: uuid.UUID | None
) -> CorpusDocument:
    """Store the gzipped record and index it. One index row per source file; a rebuild with a
    new cleaning version points it at the new object and leaves the old object in place."""
    rec = built.record
    src = rec["source"]
    key = corpus_store.key_for(src["sha256"], rec["cleaning_version"])
    await corpus_store.put_record(key, built.gz)
    labels: dict[str, int] = {}
    for ln in rec.get("lines", []):
        g = ln["label"]["gap_type"]
        labels[g] = labels.get(g, 0) + 1
    doc = await session.scalar(select(CorpusDocument).where(CorpusDocument.sha256 == src["sha256"]))
    if doc is None:
        doc = CorpusDocument(sha256=src["sha256"])
        session.add(doc)
    doc.library_file_id = library_file_id or doc.library_file_id
    doc.name = src["name"][:255]
    doc.kind = rec["kind"]
    doc.file_kind = src["file_kind"]
    doc.schema = rec["schema"]
    doc.parser = rec["parser"]["name"]
    doc.cleaning_version = rec["cleaning_version"]
    doc.storage_key = key
    doc.record_sha256 = hashlib.sha256(built.gz).hexdigest()
    doc.original_bytes = rec["sizes"]["original"]
    doc.gzip_bytes = rec["sizes"]["gzip"]
    doc.pages = src["pages"]
    doc.text_chars = rec["text"]["chars"]
    doc.lines = len(rec.get("lines", [])) or len(rec.get("facts", []))
    doc.quality_score = int(rec["quality"]["score"])
    doc.quality = rec["quality"]
    doc.labels = labels
    doc.facts = {k: v for k, v in rec.get("document", {}).items() if k != "counts"}
    doc.built_at = datetime.fromisoformat(rec["built_at"])
    await session.flush()
    return doc


async def _read_and_append(session: AsyncSession, lf: LibraryFile, kind: str, data: bytes) -> None:
    """Convert the file to its corpus record once, then grow the collections from the record."""
    built = corpus.build_record(data, lf.original_name, origin=lf.source)
    rec = built.record
    await save_corpus(session, built, library_file_id=lf.id)

    if rec["kind"] == "audit":
        rows = [
            _coerce(
                AUDIT_SCHEMA, {**r, "source_sha256": lf.sha256, "source_name": lf.original_name}
            )
            for r in rec["facts"]
        ]
        lf.kind, lf.parser = "audit", rec["parser"]["name"]
        lf.rows_added = await _append(session, COLLECTION_AUDIT, _table(AUDIT_SCHEMA, rows), lf)
        d = rec["document"]
        blocking, conflicts = int(d.get("unread_fields") or 0), int(d.get("conflicts") or 0)
        lf.facts = {
            "report_ref": d.get("report_ref"),
            "customer": d.get("customer"),
            "audit_date": d.get("audit_date"),
            "unread_fields": blocking,
            "conflicts": conflicts,
            "quality_score": built.score,
        }
        needs = blocking > 0 or conflicts > 0
        lf.status = "needs_review" if needs else "processed"
        lf.message = (
            f"{blocking} required field(s) unread and {conflicts} conflict(s). The facts were added; check them in the audit review."
            if needs
            else f"{lf.rows_added} facts added."
        )
        return

    if rec["kind"] == "boq":
        rows = [_coerce(BOQ_SCHEMA, r) for r in corpus.collection_rows(rec)]
        pairs = list(zip(rows, rec["lines"], strict=True))
        good = [r for r, _ in pairs if (r["confidence"] or 0) >= CONFIDENCE_FLOOR]
        held = [(r, ln) for r, ln in pairs if (r["confidence"] or 0) < CONFIDENCE_FLOOR]
        lf.kind, lf.parser = "boq", rec["parser"]["name"]
        lf.rows_added = await _append(session, COLLECTION_BOQ, _table(BOQ_SCHEMA, good), lf)
        lf.rows_held = len(held)
        coll = await ensure_collection(session, COLLECTION_BOQ)
        for i, (row, ln) in enumerate(held, start=1):
            session.add(
                QuarantineRow(
                    dataset_id=coll.id,
                    library_file_id=lf.id,
                    row_index=i,
                    errors=ln.get("issues") or ["Low confidence."],
                    raw={k: frame._jsonable(v) for k, v in row.items()},
                    confidence=row["confidence"] or 0,
                )
            )
        d = rec["document"]
        lf.facts = {
            "kind": d.get("doc_kind"),
            "quote_ref": d.get("quote_ref"),
            "customer": d.get("customer"),
            "quote_date": d.get("quote_date"),
            "lines": len(rows),
            "warnings": (d.get("warnings") or [])[:5],
            "quality_score": built.score,
            "repaired_lines": sum(
                1 for ln in rec["lines"] if "repaired_interleaved_heading" in ln["flags"]
            ),
        }
        lf.status = "needs_review" if held else "processed"
        lf.message = (
            f"{lf.rows_added} lines added, {len(held)} held for review."
            if held
            else f"{lf.rows_added} lines added."
        )
        return

    lf.kind, lf.status = "unknown", "skipped"
    if kind in ("docx", "json"):
        lf.message = "This is not a PrismSuite report. Its text was kept in the corpus for search."
    elif kind in ("pdf", "xlsx"):
        lf.message = "This does not look like a BOQ or quotation. Its text was kept in the corpus for search."
    else:
        lf.message = (
            "Only BOQs (PDF, Excel) and PrismSuite reports (Word, JSON) are read automatically."
        )


async def requeue_waiting(session: AsyncSession) -> int:
    """Publish the processing event again for every file still waiting. Safe: processing a file
    twice does nothing the second time."""
    count = 0
    for lf in list(
        await session.scalars(select(LibraryFile).where(LibraryFile.status == "queued"))
    ):
        outbox.publish(
            session,
            DomainEvent(
                event_type=LIBRARY_ADDED,
                aggregate_type="library_file",
                aggregate_id=str(lf.id),
                actor_id=lf.uploaded_by,
                payload={"library_file_id": str(lf.id)},
            ),
        )
        count += 1
    await session.commit()
    return count


async def list_files(
    session: AsyncSession, principal: Principal, status: str | None = None, limit: int = 100
) -> list[LibraryFile]:
    principal.require(P.DATASET_READ)
    stmt = select(LibraryFile).order_by(LibraryFile.created_at.desc()).limit(min(limit, 200))
    if status:
        stmt = stmt.where(LibraryFile.status == status)
    return list(await session.scalars(stmt))


async def retry(
    session: AsyncSession, principal: Principal, library_file_id: uuid.UUID
) -> LibraryFile:
    principal.require(P.DATASET_WRITE)
    lf = await session.get(LibraryFile, library_file_id)
    if lf is None:
        raise ValidationFailed("Library file not found.")
    if lf.status not in ("failed", "skipped"):
        raise ValidationFailed("Only failed or skipped files can be retried.")
    lf.status, lf.message = "queued", None
    outbox.publish(
        session,
        DomainEvent(
            event_type=LIBRARY_ADDED,
            aggregate_type="library_file",
            aggregate_id=str(lf.id),
            actor_id=principal.user_id,
            payload={"library_file_id": str(lf.id)},
        ),
    )
    await session.commit()
    return lf


# ------------------------------------------------------------------ watched folder


async def scan_folder(
    sessionmaker: async_sessionmaker[AsyncSession], folder: Path, *, move: bool = True
) -> dict[str, int]:
    """Pick up every supported file in `folder` (top level only). Processed files move to
    `processed/`, duplicates to `duplicates/`, unreadable ones to `failed/`."""
    counts = {"added": 0, "duplicates": 0, "failed": 0}
    if not folder.is_dir():
        return counts
    principal = _system()
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES or path.name.startswith("."):
            continue
        dest = "failed"
        try:
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            async with sessionmaker() as s:
                known = await s.scalar(select(LibraryFile.id).where(LibraryFile.sha256 == sha))
                if known:
                    counts["duplicates"] += 1
                    dest = "duplicates"
                else:
                    ref = await store_upload(
                        s,
                        principal,
                        data=data,
                        filename=path.name,
                        purpose="library",
                        project_id=None,
                    )
                    await register(
                        s,
                        file_id=ref.id,
                        name=ref.original_name,
                        sha256=ref.sha256,
                        source="folder",
                        uploaded_by=SYSTEM_USER,
                    )
                    await s.commit()
                    counts["added"] += 1
                    dest = "processed"
        except Exception as exc:  # one bad file must not stop the rest
            counts["failed"] += 1
            log.warning("library_folder_file_failed", file=path.name, error=str(exc)[:200])
        if move:
            target = folder / dest
            target.mkdir(exist_ok=True)
            shutil.move(str(path), str(target / f"{utcnow():%Y%m%d%H%M%S}_{path.name}"))
    return counts
