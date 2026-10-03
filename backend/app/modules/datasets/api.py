from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.idempotency import IdempotencyGuard, require_idempotency_key, run_idempotent
from app.core.pagination import Page, PageParams, page_params, paginate_rows
from app.core.ratelimit import Limit, check
from app.modules.datasets import corpus_service, library, service
from app.modules.datasets.engine import frame
from app.modules.datasets.models import COLLECTION_AUDIT, COLLECTION_BOQ, Dataset
from app.modules.datasets.schemas import (
    AppendRowsIn,
    CorpusDocOut,
    CorpusRecordOut,
    CreatedOut,
    DatasetFromImportIn,
    DatasetFromRowsIn,
    DatasetOut,
    DatasetUpdateIn,
    DecisionIn,
    DuplicateIn,
    FreezeIn,
    ImportPreviewIn,
    LibraryFileOut,
    LibraryUploadOut,
    PipelineIn,
    PromoteIn,
    PromotionOut,
    QuarantineActionIn,
    QuarantineOut,
    RebuildOut,
    ShareIn,
    ShareOut,
    SynonymIn,
    SynonymOut,
    VersionOut,
)
from app.modules.files.contracts import read_limited
from app.modules.identity.contracts import P, Principal, require

router = APIRouter(prefix="/datasets", tags=["datasets"])
library_router = APIRouter(prefix="/library", tags=["library"])
Session = Annotated[AsyncSession, Depends(get_session)]
Idem = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
Reader = Annotated[Principal, Depends(require(P.DATASET_READ))]
Writer = Annotated[Principal, Depends(require(P.DATASET_WRITE))]
Curator = Annotated[Principal, Depends(require(P.CATALOGUE_WRITE))]
Admin = Annotated[Principal, Depends(require(P.DATASET_ADMIN))]


def _ds(d: Any) -> DatasetOut:
    return DatasetOut.model_validate(d, from_attributes=True)


def _ver(v: Any) -> VersionOut:
    return VersionOut.model_validate(v, from_attributes=True)


# ------------------------------------------------------------------ library (the inbox)


@library_router.post("/files", response_model=LibraryUploadOut, status_code=status.HTTP_201_CREATED)
async def library_upload(
    request: Request, session: Session, principal: Writer, file: Annotated[UploadFile, File()]
) -> LibraryUploadOut:
    """Drop in an old BOQ (PDF or Excel) or a PrismSuite report (Word or JSON). It is read
    automatically. The same file is never added twice."""
    await check(
        f"user:{principal.user_id}",
        Limit("upload", get_settings().rate_limit_upload_per_minute, strict=True),
    )
    data = await read_limited(file, get_settings().max_upload_bytes)
    lf, new = await library.upload(
        session,
        principal,
        data=data,
        filename=file.filename or "upload",
        client_ip=request.state.client_ip,
    )
    return LibraryUploadOut(
        file=LibraryFileOut.model_validate(lf, from_attributes=True), duplicate=not new
    )


@library_router.get("/files", response_model=list[LibraryFileOut])
async def library_files(
    session: Session,
    principal: Reader,
    status_: Annotated[str | None, Query(alias="status", max_length=14)] = None,
) -> list[LibraryFileOut]:
    return [
        LibraryFileOut.model_validate(f, from_attributes=True)
        for f in await library.list_files(session, principal, status_)
    ]


@library_router.post("/files/{library_file_id}/retry", response_model=LibraryFileOut)
async def library_retry(
    session: Session, principal: Writer, library_file_id: uuid.UUID
) -> LibraryFileOut:
    return LibraryFileOut.model_validate(
        await library.retry(session, principal, library_file_id), from_attributes=True
    )


@library_router.get("/collections", response_model=dict[str, DatasetOut | None])
async def library_collections(session: Session, principal: Reader) -> dict[str, DatasetOut | None]:
    """The two built-in collections, or null before the first file is read."""
    out: dict[str, DatasetOut | None] = {}
    for key in (COLLECTION_BOQ, COLLECTION_AUDIT):
        d = await session.scalar(
            select(Dataset).where(
                Dataset.collection_key == key,
                Dataset.deleted_at.is_(None),
                service.visible(principal),
            )
        )
        out[key] = _ds(d) if d else None
    return out


@library_router.get("/corpus", response_model=list[CorpusDocOut])
async def corpus_list(
    session: Session,
    principal: Reader,
    kind: Annotated[Literal["boq", "audit", "other"] | None, Query()] = None,
    max_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CorpusDocOut]:
    """Every document converted to canonical JSON, newest first. Filter by kind, or by
    `max_score` to find the documents whose quality needs a person."""
    return [
        CorpusDocOut.model_validate(d, from_attributes=True)
        for d in await corpus_service.list_corpus(
            session, principal, kind=kind, max_score=max_score, limit=limit
        )
    ]


@library_router.get("/corpus/{doc_id}", response_model=CorpusRecordOut)
async def corpus_get(session: Session, principal: Reader, doc_id: uuid.UUID) -> CorpusRecordOut:
    """One document's full canonical record: text, structure, cleaned lines, labels, quality."""
    doc, rec = await corpus_service.get_corpus(session, principal, doc_id)
    return CorpusRecordOut(
        document=CorpusDocOut.model_validate(doc, from_attributes=True), record=rec
    )


@library_router.get("/analysis")
async def corpus_analysis(session: Session, principal: Reader) -> dict[str, Any]:
    """Corpus size and quality, label balance, price bands per label and flagged outliers."""
    return await corpus_service.analysis(session, principal)


@library_router.post("/rebuild", response_model=RebuildOut)
async def corpus_rebuild(session: Session, principal: Admin) -> RebuildOut:
    """Re-read every kept original with the current parsers and cleaning, then write the
    collections again as new versions. Old versions are kept."""
    return RebuildOut(**await corpus_service.rebuild(session, principal))


# ------------------------------------------------------------------ datasets


@router.get("", response_model=Page[DatasetOut])
async def list_datasets(
    session: Session,
    principal: Reader,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
    include_deleted: bool = False,
) -> Page[DatasetOut]:
    stmt = service.datasets_query(
        principal, q=q, tag=tag, include_deleted=include_deleted and principal.has(P.DATASET_ADMIN)
    )
    rows, total = await paginate_rows(session, stmt, params)
    return Page(items=[_ds(d) for d in rows], page=params.page, size=params.size, total=total)


@router.post("/import-preview")
async def import_preview(
    session: Session, principal: Writer, body: ImportPreviewIn
) -> dict[str, Any]:
    """Read an uploaded file and propose column types. Nothing is saved."""
    return await service.preview_import(session, principal, body.file_id)


@router.post("/from-import", response_model=CreatedOut, status_code=status.HTTP_201_CREATED)
async def create_from_import(
    session: Session, principal: Writer, body: DatasetFromImportIn, guard: Idem
) -> Any:
    async def work() -> CreatedOut:
        ds, v, n = await service.create_from_import(
            session,
            principal,
            file_id=body.file_id,
            name=body.name,
            description=body.description,
            tags=body.tags,
            schema=[c.model_dump() for c in body.schema_] if body.schema_ else None,
            rules=body.rules,
        )
        return CreatedOut(dataset=_ds(ds), version=_ver(v), quarantined=n)

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@router.post("/from-rows", response_model=CreatedOut, status_code=status.HTTP_201_CREATED)
async def create_from_rows(
    session: Session, principal: Writer, body: DatasetFromRowsIn, guard: Idem
) -> Any:
    async def work() -> CreatedOut:
        ds, v, n = await service.create_from_rows(
            session,
            principal,
            name=body.name,
            description=body.description,
            tags=body.tags,
            columns=[c.model_dump() for c in body.columns],
            rows=body.rows,
        )
        return CreatedOut(dataset=_ds(ds), version=_ver(v), quarantined=n)

    return await run_idempotent(guard, str(principal.user_id), 201, work)


@router.get("/synonyms", response_model=list[SynonymOut])
async def synonyms(session: Session, principal: Reader) -> list[SynonymOut]:
    return [
        SynonymOut.model_validate(s, from_attributes=True)
        for s in await service.list_synonyms(session, principal)
    ]


@router.post("/synonyms", response_model=SynonymOut, status_code=status.HTTP_201_CREATED)
async def add_synonym(session: Session, principal: Curator, body: SynonymIn) -> SynonymOut:
    s = await service.add_synonym(
        session, principal, domain=body.domain, canonical=body.canonical, alias=body.alias
    )
    return SynonymOut.model_validate(s, from_attributes=True)


@router.get("/promotions", response_model=list[PromotionOut])
async def promotions(
    session: Session,
    principal: Curator,
    status_: Annotated[
        Literal["pending", "approved", "rejected"], Query(alias="status")
    ] = "pending",
) -> list[PromotionOut]:
    return [
        PromotionOut.model_validate(p, from_attributes=True)
        for p in await service.list_promotions(session, principal, status_)
    ]


@router.post("/promotions/{promotion_id}/decision", response_model=PromotionOut)
async def decide_promotion(
    session: Session, principal: Curator, promotion_id: uuid.UUID, body: DecisionIn
) -> PromotionOut:
    p = await service.decide_promotion(
        session, principal, promotion_id, approve=body.approve, note=body.note
    )
    return PromotionOut.model_validate(p, from_attributes=True)


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(session: Session, principal: Reader, dataset_id: uuid.UUID) -> DatasetOut:
    return _ds(await service.get_dataset(session, principal, dataset_id))


@router.patch("/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    session: Session, principal: Writer, dataset_id: uuid.UUID, body: DatasetUpdateIn
) -> DatasetOut:
    ds = await service.update_dataset(
        session,
        principal,
        dataset_id,
        version=body.version,
        name=body.name,
        description=body.description,
        tags=body.tags,
        rules=body.rules,
    )
    return _ds(ds)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(session: Session, principal: Writer, dataset_id: uuid.UUID) -> Response:
    await service.soft_delete(session, principal, dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{dataset_id}/restore", response_model=DatasetOut)
async def restore_dataset(session: Session, principal: Writer, dataset_id: uuid.UUID) -> DatasetOut:
    return _ds(await service.restore(session, principal, dataset_id))


@router.post(
    "/{dataset_id}/duplicate", response_model=DatasetOut, status_code=status.HTTP_201_CREATED
)
async def duplicate(
    session: Session, principal: Writer, dataset_id: uuid.UUID, body: DuplicateIn
) -> DatasetOut:
    return _ds(await service.duplicate(session, principal, dataset_id, body.name))


@router.get("/{dataset_id}/versions", response_model=list[VersionOut])
async def versions(session: Session, principal: Reader, dataset_id: uuid.UUID) -> list[VersionOut]:
    ds = await service.get_dataset(session, principal, dataset_id)
    return [_ver(v) for v in await service.list_versions(session, ds)]


@router.get("/{dataset_id}/rows")
async def rows(
    session: Session,
    principal: Reader,
    dataset_id: uuid.UUID,
    version: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0, le=2_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=frame.PREVIEW_CAP)] = 100,
) -> dict[str, Any]:
    return await service.preview_rows(session, principal, dataset_id, version, offset, limit)


@router.post("/{dataset_id}/rows", response_model=CreatedOut)
async def append_rows(
    session: Session, principal: Writer, dataset_id: uuid.UUID, body: AppendRowsIn
) -> CreatedOut:
    v, n = await service.append_rows(session, principal, dataset_id, body.rows, body.version)
    ds = await service.get_dataset(session, principal, dataset_id)
    return CreatedOut(dataset=_ds(ds), version=_ver(v), quarantined=n)


@router.post("/{dataset_id}/pipeline")
async def run_pipeline(
    session: Session, principal: Writer, dataset_id: uuid.UUID, body: PipelineIn
) -> dict[str, Any]:
    """Apply a list of whitelisted steps. By default a dry run that returns a preview."""
    table, v = await service.run_steps(
        session,
        principal,
        dataset_id,
        version=body.version,
        raw_steps=body.steps,
        save_as=body.save_as,
        dry_run=body.dry_run,
    )
    return {
        "columns": frame.schema_of(table),
        "rows": frame.rows(table, 100),
        "total": table.num_rows,
        "saved": _ver(v).model_dump(mode="json") if v else None,
    }


@router.get("/{dataset_id}/analysis")
async def analysis(
    session: Session,
    principal: Reader,
    dataset_id: uuid.UUID,
    version: Annotated[int | None, Query(ge=1)] = None,
    outlier_z: Annotated[float, Query(ge=1, le=10)] = 3.0,
    iqr_k: Annotated[float, Query(ge=0.5, le=5)] = 1.5,
) -> dict[str, Any]:
    return await service.analysis(
        session, principal, dataset_id, version, outlier_z=outlier_z, iqr_k=iqr_k
    )


@router.get("/{dataset_id}/chart")
async def chart(
    session: Session,
    principal: Reader,
    dataset_id: uuid.UUID,
    kind: Literal["histogram", "box", "scatter", "bar", "line", "heatmap", "pivot"],
    version: Annotated[int | None, Query(ge=1)] = None,
    x: Annotated[str | None, Query(max_length=120)] = None,
    y: Annotated[str | None, Query(max_length=120)] = None,
    group: Annotated[str | None, Query(max_length=120)] = None,
    agg: Literal["sum", "avg", "min", "max", "count", "median"] = "sum",
    grain: Literal["day", "week", "month", "quarter", "year"] = "month",
    bins: Annotated[int, Query(ge=2, le=100)] = 20,
) -> dict[str, Any]:
    return await service.chart(
        session,
        principal,
        dataset_id,
        version,
        kind=kind,
        x=x,
        y=y,
        group=group,
        agg=agg,
        grain=grain,
        bins=bins,
    )


@router.get("/{dataset_id}/diff")
async def diff(
    session: Session,
    principal: Reader,
    dataset_id: uuid.UUID,
    a: Annotated[int, Query(ge=1)],
    b: Annotated[int, Query(ge=1)],
) -> dict[str, Any]:
    return await service.diff_versions(session, principal, dataset_id, a, b)


@router.get("/{dataset_id}/export")
async def export(
    session: Session,
    principal: Reader,
    dataset_id: uuid.UUID,
    fmt: Literal["csv", "xlsx", "parquet"] = "csv",
    version: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    data, mime, name = await service.export(session, principal, dataset_id, version, fmt)
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/{dataset_id}/freeze", response_model=VersionOut)
async def freeze(
    session: Session, principal: Writer, dataset_id: uuid.UUID, body: FreezeIn
) -> VersionOut:
    return _ver(
        await service.freeze_for_training(
            session,
            principal,
            dataset_id,
            body.version,
            source=body.source,
            known_issues=body.known_issues,
        )
    )


@router.get("/{dataset_id}/shares", response_model=list[ShareOut])
async def shares(session: Session, principal: Reader, dataset_id: uuid.UUID) -> list[ShareOut]:
    return [
        ShareOut.model_validate(s, from_attributes=True)
        for s in await service.list_shares(session, principal, dataset_id)
    ]


@router.put("/{dataset_id}/shares", response_model=ShareOut)
async def share(
    session: Session, principal: Writer, dataset_id: uuid.UUID, body: ShareIn
) -> ShareOut:
    s = await service.share(
        session, principal, dataset_id, kind=body.kind, target=body.target, access=body.access
    )
    return ShareOut.model_validate(s, from_attributes=True)


@router.delete("/{dataset_id}/shares/{kind}/{target}", status_code=status.HTTP_204_NO_CONTENT)
async def unshare(
    session: Session,
    principal: Writer,
    dataset_id: uuid.UUID,
    kind: Literal["user", "role"],
    target: str,
) -> Response:
    await service.unshare(session, principal, dataset_id, kind=kind, target=target)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{dataset_id}/quarantine", response_model=list[QuarantineOut])
async def quarantine(
    session: Session,
    principal: Reader,
    dataset_id: uuid.UUID,
    status_: Annotated[Literal["open", "fixed", "discarded"], Query(alias="status")] = "open",
) -> list[QuarantineOut]:
    return [
        QuarantineOut.model_validate(q, from_attributes=True)
        for q in await service.list_quarantine(session, principal, dataset_id, status_)
    ]


@router.post("/{dataset_id}/quarantine/{row_id}", response_model=QuarantineOut)
async def resolve_quarantine(
    session: Session,
    principal: Writer,
    dataset_id: uuid.UUID,
    row_id: uuid.UUID,
    body: QuarantineActionIn,
) -> QuarantineOut:
    q = await service.resolve_quarantine(
        session, principal, dataset_id, row_id, action=body.action, values=body.values
    )
    return QuarantineOut.model_validate(q, from_attributes=True)


@router.post(
    "/{dataset_id}/promotions",
    response_model=list[PromotionOut],
    status_code=status.HTTP_201_CREATED,
)
async def submit_promotions(
    session: Session, principal: Writer, dataset_id: uuid.UUID, body: PromoteIn
) -> list[PromotionOut]:
    """Propose rows for the master catalogue. A different person must approve each one."""
    items = await service.submit_promotions(
        session,
        principal,
        dataset_id,
        body.version,
        mapping=body.mapping,
        constants=body.constants,
        row_numbers=body.row_numbers,
    )
    return [PromotionOut.model_validate(i, from_attributes=True) for i in items]


routers = [router, library_router]
