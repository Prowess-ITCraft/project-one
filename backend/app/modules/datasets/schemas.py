from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
ColType = Literal["string", "int", "decimal", "float", "bool", "date", "timestamp"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ColumnIn(_In):
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    type: ColType = "string"


class ImportPreviewIn(_In):
    file_id: uuid.UUID


class DatasetFromImportIn(_In):
    file_id: uuid.UUID
    name: Name
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    schema_: list[ColumnIn] | None = Field(default=None, alias="schema")
    rules: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DatasetFromRowsIn(_In):
    name: Name
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    columns: list[ColumnIn] = Field(min_length=1, max_length=200)
    rows: list[list[Any]] = Field(min_length=1, max_length=5000)


class AppendRowsIn(_In):
    rows: list[list[Any]] = Field(min_length=1, max_length=5000)
    version: int = Field(ge=1)


class DatasetUpdateIn(_In):
    version: int = Field(ge=1)
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    tags: list[Tag] | None = Field(default=None, max_length=20)
    rules: list[dict[str, Any]] | None = Field(default=None, max_length=50)


class DuplicateIn(_In):
    name: Name


class PipelineIn(_In):
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    version: int | None = Field(
        default=None, ge=1, description="Source version, latest when omitted"
    )
    save_as: Name | None = Field(
        default=None, description="Create a new dataset instead of a new version"
    )
    dry_run: bool = Field(default=True, description="Return a preview and save nothing")


class ShareIn(_In):
    kind: Literal["user", "role"]
    target: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    access: Literal["view", "edit"]


class FreezeIn(_In):
    version: int | None = Field(default=None, ge=1)
    source: Annotated[str, StringConstraints(min_length=3, max_length=300)]
    known_issues: Annotated[str, StringConstraints(max_length=1000)] | None = None


class QuarantineActionIn(_In):
    action: Literal["fix", "discard"]
    values: dict[str, Any] | None = None


class SynonymIn(_In):
    domain: Literal["vendor", "product"]
    canonical: Annotated[str, StringConstraints(min_length=2, max_length=160)]
    alias: Annotated[str, StringConstraints(min_length=1, max_length=160)]


class PromoteIn(_In):
    version: int | None = Field(default=None, ge=1)
    mapping: dict[
        Annotated[str, StringConstraints(max_length=40)],
        Annotated[str, StringConstraints(max_length=120)],
    ] = Field(min_length=1)
    constants: dict[str, Any] = Field(default_factory=dict)
    row_numbers: list[int] | None = Field(default=None, max_length=500)


class DecisionIn(_In):
    approve: bool
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


# ------------------------------------------------------------------ output


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    tags: list[str]
    collection_key: str | None
    owner_id: uuid.UUID
    latest_version: int
    version: int
    validation_rules: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: int
    row_count: int
    columns: list[dict[str, Any]]
    lineage: list[dict[str, Any]]
    summary: str
    created_by: uuid.UUID
    created_at: datetime
    frozen_for_training: bool
    data_card: dict[str, Any] | None


class CreatedOut(BaseModel):
    dataset: DatasetOut
    version: VersionOut
    quarantined: int


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    principal: str
    access: str
    granted_at: datetime


class QuarantineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    row_index: int
    errors: list[str]
    raw: dict[str, Any]
    confidence: float | None
    status: str
    library_file_id: uuid.UUID | None
    created_at: datetime


class SynonymOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    domain: str
    canonical: str
    alias: str


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    row: dict[str, Any]
    proposed: dict[str, Any]
    status: str
    submitted_by: uuid.UUID
    reviewed_by: uuid.UUID | None
    note: str | None
    catalogue_item_id: uuid.UUID | None
    created_at: datetime


class LibraryFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str
    sha256: str
    source: str
    kind: str | None
    status: str
    parser: str | None
    rows_added: int
    rows_held: int
    message: str | None
    facts: dict[str, Any]
    created_at: datetime
    processed_at: datetime | None


class LibraryUploadOut(BaseModel):
    file: LibraryFileOut
    duplicate: bool


class CorpusDocOut(BaseModel):
    """One document in the corpus: the index row (ADR 0014)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    library_file_id: uuid.UUID | None
    sha256: str
    name: str
    kind: str
    file_kind: str
    parser: str | None
    cleaning_version: str
    original_bytes: int
    gzip_bytes: int
    pages: int
    text_chars: int
    lines: int
    quality_score: int
    quality: dict[str, Any]
    labels: dict[str, int]
    facts: dict[str, Any]
    original_state: str
    built_at: datetime


class CorpusRecordOut(BaseModel):
    document: CorpusDocOut
    record: dict[str, Any]


class RebuildOut(BaseModel):
    rebuilt: int
    reused: int
    failed: int
