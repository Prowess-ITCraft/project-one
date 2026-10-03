"""Content-type detection from bytes, never from the client's Content-Type header.

The file extension must agree with what the bytes are. Office files are zip containers, so
they are opened (with size and ratio limits against zip bombs) and checked for the right parts.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass

MAX_ZIP_ENTRIES = 5000
MAX_ZIP_UNCOMPRESSED = 300 * 1024 * 1024
MAX_ZIP_RATIO = 200


@dataclass(frozen=True)
class FileKind:
    code: str
    mime: str
    extensions: tuple[str, ...]


DOCX = FileKind(
    "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", (".docx",)
)
XLSX = FileKind(
    "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (".xlsx",)
)
PDF = FileKind("pdf", "application/pdf", (".pdf",))
PNG = FileKind("png", "image/png", (".png",))
JPEG = FileKind("jpeg", "image/jpeg", (".jpg", ".jpeg"))
WEBP = FileKind("webp", "image/webp", (".webp",))
PARQUET = FileKind("parquet", "application/vnd.apache.parquet", (".parquet",))
JSON = FileKind("json", "application/json", (".json",))
CSV = FileKind("csv", "text/csv", (".csv",))
TEXT = FileKind("text", "text/plain", (".txt", ".cfg", ".conf", ".log", ".exp", ".xml"))
ZIP = FileKind("zip", "application/zip", (".zip",))

KINDS = {k.code: k for k in (DOCX, XLSX, PDF, PNG, JPEG, WEBP, PARQUET, JSON, CSV, TEXT, ZIP)}


class SniffError(ValueError):
    pass


def _zip_kind(data: bytes) -> FileKind:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SniffError("The file looks like a zip archive but is damaged.") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise SniffError("The archive has too many entries.")
        total = sum(i.file_size for i in infos)
        packed = sum(i.compress_size for i in infos) or 1
        if total > MAX_ZIP_UNCOMPRESSED or total / packed > MAX_ZIP_RATIO:
            raise SniffError("The archive expands to an unsafe size.")
        names = {i.filename for i in infos}
        if "[Content_Types].xml" in names:
            if any(n.startswith("word/") for n in names):
                return DOCX
            if any(n.startswith("xl/") for n in names):
                return XLSX
            raise SniffError("This Office file type is not supported.")
        return ZIP


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:65536]:
        return False
    try:
        data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        # A multi-byte character may be cut at the boundary; retry a little shorter.
        try:
            data[:65530].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return True


def detect(data: bytes) -> FileKind:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data[:4] == b"PAR1" and data[-4:] == b"PAR1":
        return PARQUET
    if data.startswith(b"PK\x03\x04"):
        return _zip_kind(data)
    if _is_text(data):
        stripped = data.lstrip()[:1]
        if stripped in (b"{", b"["):
            try:
                json.loads(data)
                return JSON
            except ValueError:
                pass
        return TEXT
    raise SniffError("This file type is not recognised.")


def check(data: bytes, filename: str, allowed: frozenset[str]) -> FileKind:
    """Detect the type and confirm the extension matches and the type is allowed here."""
    if not data:
        raise SniffError("The file is empty.")
    kind = detect(data)
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if kind is TEXT and ext == ".csv":
        kind = CSV
    if kind is JSON and ext != ".json" and "text" in allowed:
        kind = TEXT
    if kind.code not in allowed:
        raise SniffError(f"{kind.code.upper()} files are not accepted here.")
    if ext not in kind.extensions:
        raise SniffError(
            f"The file name ends in {ext or '(nothing)'} but the content is {kind.code.upper()}."
        )
    return kind
