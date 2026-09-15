from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from disclosure_impact_agent.models import DocumentFormat

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ZIP_ENTRIES = 20
MAX_ZIP_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_ZIP_RATIO = 100


class UnsafeUploadError(ValueError):
    pass


@dataclass(frozen=True)
class UploadPart:
    filename: str
    content: bytes
    document_format: DocumentFormat


def _format_for(filename: str) -> DocumentFormat:
    suffix = PurePosixPath(filename.lower()).suffix
    formats = {".html": DocumentFormat.HTML, ".htm": DocumentFormat.HTML, ".xml": DocumentFormat.XML, ".txt": DocumentFormat.TEXT}
    if suffix not in formats:
        raise UnsafeUploadError(f"Unsupported upload extension: {suffix or '(none)'}")
    return formats[suffix]


def load_upload(filename: str, content: bytes) -> list[UploadPart]:
    if not content:
        raise UnsafeUploadError("Upload is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UnsafeUploadError("Upload exceeds size limit")
    if PurePosixPath(filename.lower()).suffix != ".zip":
        return [UploadPart(filename=filename, content=content, document_format=_format_for(filename))]
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise UnsafeUploadError("ZIP signature or central directory is invalid")
    parts: list[UploadPart] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise UnsafeUploadError("ZIP has too many entries")
        for info in entries:
            path = PurePosixPath(info.filename)
            if info.is_dir():
                continue
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise UnsafeUploadError("ZIP path traversal detected")
            total += info.file_size
            if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise UnsafeUploadError("ZIP uncompressed size limit exceeded")
            if info.compress_size == 0 and info.file_size > 0:
                raise UnsafeUploadError("Suspicious ZIP compression ratio")
            if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO:
                raise UnsafeUploadError("Suspicious ZIP compression ratio")
            document_format = _format_for(info.filename)
            extracted = archive.read(info)
            if len(extracted) != info.file_size:
                raise UnsafeUploadError("ZIP entry size mismatch")
            parts.append(UploadPart(filename=info.filename, content=extracted, document_format=document_format))
    if not parts:
        raise UnsafeUploadError("ZIP contains no supported document")
    return parts
