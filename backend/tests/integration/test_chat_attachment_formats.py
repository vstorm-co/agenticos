"""A new-format upload persists a canonical row, and a legacy row still reads (#1591).

Against a real database because the assertion is about the stored `ChatFile`: an
octet-stream TIFF must land as `image/tiff` (the resolved MIME, not the declared
header), so the download route and the inline-conversion path read one trustworthy
field. A row written *before* this change keeps its declared MIME, and every reader
must tolerate both shapes.
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image

from app.db.models.chat_file import ChatFile
from app.db.models.user import User
from app.services import file_upload as fu
from app.services.file_storage import LocalFileStorage

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _member(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _tiff() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="TIFF")
    return buffer.getvalue()


def _ods() -> bytes:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    document = OpenDocumentSpreadsheet()
    table = Table(name="S")
    row = TableRow()
    for value in ("a", "b"):
        cell = TableCell()
        cell.addElement(P(text=value))
        row.addElement(cell)
    table.addElement(row)
    document.spreadsheet.addElement(table)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class TestANewFormatPersistsACanonicalRow:
    async def test_an_octet_stream_tiff_is_stored_as_image_tiff(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(fu, "get_file_storage", lambda: LocalFileStorage(base_dir=tmp_path))
        owner = await _member(db)

        stored = await fu.FileUploadService(db).upload(
            user_id=owner.id,
            file_data=_tiff(),
            filename="scan.tiff",
            content_type="application/octet-stream",
        )

        assert stored.mime_type == "image/tiff"  # canonical, not the octet-stream declared
        assert stored.file_type == "image"
        assert stored.parsed_content is None  # an image carries no extracted text

    async def test_an_octet_stream_ods_is_stored_with_its_text(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(fu, "get_file_storage", lambda: LocalFileStorage(base_dir=tmp_path))
        owner = await _member(db)

        stored = await fu.FileUploadService(db).upload(
            user_id=owner.id,
            file_data=_ods(),
            filename="book.ods",
            content_type="application/octet-stream",
        )

        assert stored.mime_type == "application/vnd.oasis.opendocument.spreadsheet"
        assert stored.file_type == "spreadsheet"
        assert stored.parsed_content is not None and "a\tb" in stored.parsed_content


class TestALegacyRowStillReads:
    async def test_a_pre_change_octet_stream_tiff_row_serves_and_does_not_convert(
        self, db, tmp_path, monkeypatch
    ):
        """A row from before this shipped keeps its *declared* octet-stream MIME.
        The download route serves it and `_inline_images` reaches it without error —
        the TIFF is served as a download and is not PNG-converted."""
        from app.services import attachments as attachments_module

        storage = LocalFileStorage(base_dir=tmp_path)
        monkeypatch.setattr(fu, "get_file_storage", lambda: storage)
        monkeypatch.setattr(attachments_module, "get_file_storage", lambda: storage)
        owner = await _member(db)
        path = await storage.save(str(owner.id), "old.tiff", _tiff())
        legacy = ChatFile(
            id=uuid.uuid4(),
            user_id=owner.id,
            filename="old.tiff",
            mime_type="application/octet-stream",  # the pre-change shape
            size=64,
            storage_path=path,
            file_type="image",
        )
        db.add(legacy)
        await db.flush()

        router = attachments_module.AttachmentRouter()
        result = await router._inline_images(legacy, None)

        # Reached without error, served as-is (octet-stream), not converted to PNG.
        assert len(result.images) == 1
        assert result.images[0].media_type == "application/octet-stream"
        assert result.note is None
