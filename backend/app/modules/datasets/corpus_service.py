"""Reading, analysing, rebuilding and pruning the document corpus (ADR 0014).

- `list_corpus` and `get_corpus`: the index rows and one full record.
- `analysis`: the state of the data as a whole: sizes saved, quality, label balance, price
  bands and outliers per label. This is the exploratory analysis the BOQ engine and the ML phase
  rely on.
- `rebuild`: re-run extraction and cleaning over every kept original (after a parser or
  cleaning change) and write fresh collection versions. Old versions stay.
- `purge_originals`: the retention rule. Off by default.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from typing import Any

import pyarrow as pa
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.timeutil import utcnow
from app.modules.audit_log.contracts import AuditContext, record
from app.modules.datasets import cleaning, corpus, corpus_store, library, quality, service
from app.modules.datasets.models import (
    COLLECTION_AUDIT,
    COLLECTION_BOQ,
    SYSTEM_USER,
    CorpusDocument,
    Dataset,
    LibraryFile,
)
from app.modules.files.contracts import purge_library_original, read_file_system
from app.modules.identity.contracts import P, Principal, audit_context

log = structlog.get_logger(__name__)
LOW_QUALITY = 70


async def list_corpus(
    session: AsyncSession,
    principal: Principal,
    *,
    kind: str | None = None,
    max_score: int | None = None,
    limit: int = 100,
) -> list[CorpusDocument]:
    principal.require(P.DATASET_READ)
    stmt = select(CorpusDocument).order_by(CorpusDocument.created_at.desc()).limit(min(limit, 500))
    if kind:
        stmt = stmt.where(CorpusDocument.kind == kind)
    if max_score is not None:
        stmt = stmt.where(CorpusDocument.quality_score <= max_score)
    return list(await session.scalars(stmt))


async def get_corpus(
    session: AsyncSession, principal: Principal, doc_id: uuid.UUID
) -> tuple[CorpusDocument, dict[str, Any]]:
    principal.require(P.DATASET_READ)
    doc = await session.get(CorpusDocument, doc_id)
    if doc is None:
        raise NotFound("Corpus document not found.")
    gz = await corpus_store.get_record(doc.storage_key)
    if hashlib.sha256(gz).hexdigest() != doc.record_sha256:
        log.error("corpus_integrity_mismatch", doc=str(doc.id))
        raise NotFound("The stored record failed its integrity check. Rebuild the corpus.")
    return doc, corpus.read_gz(gz)


async def _collection_rows(session: AsyncSession, key: str) -> list[dict[str, Any]]:
    ds = await session.scalar(
        select(Dataset).where(Dataset.collection_key == key, Dataset.deleted_at.is_(None))
    )
    if ds is None or ds.latest_version == 0:
        return []
    table = await service.load_table(await service.get_version(session, ds))
    return list(table.to_pylist())


async def analysis(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    """Corpus totals, quality and the historical BOQ analysis by label."""
    principal.require(P.DATASET_READ)
    by_kind = {
        k: {
            "documents": n,
            "original_bytes": int(o or 0),
            "gzip_bytes": int(g or 0),
            "mean_quality": round(float(q or 0), 1),
        }
        for k, n, o, g, q in await session.execute(
            select(
                CorpusDocument.kind,
                func.count(),
                func.sum(CorpusDocument.original_bytes),
                func.sum(CorpusDocument.gzip_bytes),
                func.avg(CorpusDocument.quality_score),
            ).group_by(CorpusDocument.kind)
        )
    }
    orig = sum(v["original_bytes"] for v in by_kind.values())
    gz = sum(v["gzip_bytes"] for v in by_kind.values())
    low = list(
        await session.scalars(
            select(CorpusDocument)
            .where(CorpusDocument.quality_score < LOW_QUALITY)
            .order_by(CorpusDocument.quality_score)
            .limit(20)
        )
    )
    rows = await _collection_rows(session, COLLECTION_BOQ)
    for r in rows:  # rows read before the corpus existed have no label yet
        if not r.get("gap_type"):
            lab = cleaning.label_line(r.get("component") or "", r.get("description") or "")
            r["gap_type"], r["line_role"] = lab.gap_type, lab.line_role
    return {
        "corpus": {
            "documents": sum(v["documents"] for v in by_kind.values()),
            "by_kind": by_kind,
            "original_bytes": orig,
            "gzip_bytes": gz,
            "saved_share": round(1 - gz / orig, 4) if orig else 0.0,
            "low_quality": [
                {
                    "id": str(d.id),
                    "name": d.name,
                    "kind": d.kind,
                    "score": d.quality_score,
                    "issues": d.quality.get("issues", [])[:3],
                }
                for d in low
            ],
            "cleaning_version": cleaning.CLEANING_VERSION,
        },
        "boq": quality.analyse_lines(rows),
        "taxonomy": cleaning.TAXONOMY,
    }


async def rebuild(session: AsyncSession, principal: Principal | None = None) -> dict[str, int]:
    """Re-convert every library file with the current parsers and cleaning, then write each
    built-in collection again as one new version built only from corpus records.

    Kept originals are re-read; for purged ones the stored record is reused. Safe to run again."""
    if principal is not None:
        principal.require(P.DATASET_ADMIN)
    counts = {"rebuilt": 0, "reused": 0, "failed": 0}
    boq_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for lf in list(await session.scalars(select(LibraryFile).order_by(LibraryFile.created_at))):
        doc = await session.scalar(select(CorpusDocument).where(CorpusDocument.sha256 == lf.sha256))
        rec: dict[str, Any] | None = None
        if lf.file_id is not None and (doc is None or doc.original_state == "kept"):
            try:
                _, data = await read_file_system(session, lf.file_id)
                built = corpus.build_record(data, lf.original_name, origin=lf.source)
                await library.save_corpus(session, built, library_file_id=lf.id)
                rec = built.record
                counts["rebuilt"] += 1
            except Exception as exc:  # one bad file must not stop the rebuild
                counts["failed"] += 1
                log.warning("corpus_rebuild_failed", file=lf.original_name, error=str(exc)[:200])
        if rec is None and doc is not None:
            rec = corpus.read_gz(await corpus_store.get_record(doc.storage_key))
            counts["reused"] += 1
        if rec is None:
            continue
        if rec["kind"] == "boq":
            boq_rows += [
                r
                for r in (
                    library._coerce(library.BOQ_SCHEMA, x) for x in corpus.collection_rows(rec)
                )
                if (r["confidence"] or 0) >= library.CONFIDENCE_FLOOR
            ]
        elif rec["kind"] == "audit":
            src = rec["source"]
            audit_rows += [
                library._coerce(
                    library.AUDIT_SCHEMA,
                    {**r, "source_sha256": src["sha256"], "source_name": src["name"]},
                )
                for r in rec["facts"]
            ]
    for key, schema, rows in (
        (COLLECTION_BOQ, library.BOQ_SCHEMA, boq_rows),
        (COLLECTION_AUDIT, library.AUDIT_SCHEMA, audit_rows),
    ):
        ds = await library.ensure_collection(session, key)
        latest = await service.get_version(session, ds)
        await service.write_version(
            session,
            ds,
            library._table(schema, rows) if rows else pa.Table.from_pylist([], schema=schema),
            step={
                "op": "corpus_rebuild",
                "cleaning_version": cleaning.CLEANING_VERSION,
                "rows": len(rows),
            },
            summary=f"Rebuilt from the corpus (cleaning v{cleaning.CLEANING_VERSION})",
            actor_id=principal.user_id if principal else SYSTEM_USER,
            parent=latest,
        )
    await record(
        session,
        audit_context(principal) if principal else AuditContext.system("corpus"),
        action="corpus_rebuild",
        entity_type="corpus",
        entity_id="all",
        after=counts,
        only_changes=False,
    )
    await session.commit()
    return counts


async def purge_originals(session: AsyncSession, *, days: int | None = None) -> int:
    """Delete originals older than the retention period, but only after the stored record is
    read back and its checksum matches. 0 days (the default setting) does nothing."""
    keep_days = get_settings().corpus_originals_retention_days if days is None else days
    if keep_days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=keep_days)
    purged = 0
    docs = await session.scalars(
        select(CorpusDocument).where(
            CorpusDocument.original_state == "kept", CorpusDocument.created_at < cutoff
        )
    )
    for doc in list(docs):
        lf = await session.get(LibraryFile, doc.library_file_id) if doc.library_file_id else None
        if lf is None or lf.file_id is None:
            continue
        gz = await corpus_store.get_record(doc.storage_key)
        if hashlib.sha256(gz).hexdigest() != doc.record_sha256:
            log.error("corpus_purge_skipped_integrity", doc=str(doc.id))
            continue
        if await purge_library_original(session, lf.file_id, f"Corpus retention {keep_days} days"):
            doc.original_state = "purged"
            purged += 1
            await record(
                session,
                AuditContext.system("corpus"),
                action="corpus_purge_original",
                entity_type="corpus_document",
                entity_id=doc.id,
                after={"name": doc.name, "sha256": doc.sha256, "days": keep_days},
                only_changes=False,
            )
    await session.commit()
    return purged
