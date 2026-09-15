import io
import zipfile

import pytest

from disclosure_impact_agent.models import DocumentFormat
from disclosure_impact_agent.uploads import MAX_UPLOAD_BYTES, UnsafeUploadError, load_upload


def make_zip(entries: dict[str, bytes], compression=zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_safe_zip_returns_supported_parts_without_extracting_to_disk():
    payload = make_zip({"document.html": b"<html></html>", "notes.txt": b"memo"})
    parts = load_upload("dart.zip", payload)

    assert [(part.filename, part.document_format) for part in parts] == [
        ("document.html", DocumentFormat.HTML), ("notes.txt", DocumentFormat.TEXT)
    ]


def test_zip_path_traversal_is_rejected():
    payload = make_zip({"../escape.html": b"bad"})
    with pytest.raises(UnsafeUploadError, match="traversal"):
        load_upload("dart.zip", payload)


def test_oversized_upload_is_rejected_before_parsing():
    with pytest.raises(UnsafeUploadError, match="size limit"):
        load_upload("large.html", b"x" * (MAX_UPLOAD_BYTES + 1))


def test_unknown_extension_and_fake_zip_are_rejected():
    with pytest.raises(UnsafeUploadError, match="extension"):
        load_upload("filing.pdf", b"not supported")
    with pytest.raises(UnsafeUploadError, match="ZIP"):
        load_upload("document.zip", b"not a zip")
