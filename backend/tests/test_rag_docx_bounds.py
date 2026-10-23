"""A DOCX parsed for a knowledge base is unzipped under the chat's bounds (#2248).

A DOCX is a ZIP: a few megabytes of upload can inflate to gigabytes in
python-docx, a child the memory watchdog kills on every attempt. Under the bound
it is the document's own failure - a `ValueError` - and no process dies.
"""

import io
import zipfile
from pathlib import Path

import pytest

from app.core import config as config_module
from app.services.rag.documents import DocxDocumentParser

pytestmark = pytest.mark.anyio


def _docx(path: Path, body: str) -> Path:
    from docx import Document

    document = Document()
    document.add_paragraph(body)
    document.save(str(path))
    return path


async def test_an_ordinary_docx_is_read(tmp_path: Path) -> None:
    parsed = await DocxDocumentParser().parse(_docx(tmp_path / "memo.docx", "Quarterly memo"))

    assert "Quarterly memo" in parsed.pages[0].content


async def test_a_docx_that_inflates_past_the_bound_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_module.settings, "CHAT_ARCHIVE_MEMBER_MAX_BYTES", 50_000)
    path = _docx(tmp_path / "bomb.docx", "x")
    buffer = io.BytesIO(path.read_bytes())
    with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/padding.xml", b"\x00" * 1_000_000)
    path.write_bytes(buffer.getvalue())

    with pytest.raises(ValueError, match="too large"):
        await DocxDocumentParser().parse(path)
