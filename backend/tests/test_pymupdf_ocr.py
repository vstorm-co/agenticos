"""The PyMuPDF OCR fallback and the loop it runs on (#550).

`_ocr_page` used to drive the image describer through a second event loop
(`asyncio.new_event_loop().run_until_complete`) while `parse` was already
awaiting on the running one. The nested loop raised `RuntimeError`, a broad
`except` logged it as "LLM OCR failed", and every scanned page OCR'd to
`""` - the document indexed empty, indistinguishable from a PDF that
genuinely had no text.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from app.services.rag.documents import PyMuPDFParser
from app.services.rag.image_describer import BaseImageDescriber

pytestmark = pytest.mark.anyio


class LoopRecordingDescriber(BaseImageDescriber):
    def __init__(self, text: str) -> None:
        self.text = text
        self.loops: list[asyncio.AbstractEventLoop] = []

    async def describe(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        self.loops.append(asyncio.get_running_loop())
        return self.text


def _scanned_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


async def test_a_scanned_page_indexes_with_its_ocr_text(tmp_path: Path) -> None:
    describer = LoopRecordingDescriber("Text the vision model recovered from the scan.")
    parser = PyMuPDFParser(enable_ocr=True, image_describer=describer)

    document = await parser.parse(_scanned_pdf(tmp_path / "scan.pdf"))

    assert document.pages[0].content == describer.text


async def test_ocr_runs_on_the_callers_loop_not_a_nested_one(tmp_path: Path) -> None:
    describer = LoopRecordingDescriber("Recovered text long enough to beat the empty page.")
    parser = PyMuPDFParser(enable_ocr=True, image_describer=describer)

    await parser.parse(_scanned_pdf(tmp_path / "scan.pdf"))

    assert describer.loops == [asyncio.get_running_loop()]


async def test_a_page_that_cannot_render_skips_ocr_without_failing_the_parse() -> None:
    describer = LoopRecordingDescriber("never reached")
    parser = PyMuPDFParser(enable_ocr=True, image_describer=describer)
    page = SimpleNamespace(
        number=0,
        get_pixmap=lambda dpi: (_ for _ in ()).throw(RuntimeError("render failed")),
    )

    assert await parser._ocr_page(page, describer) == ""
    assert describer.loops == []


async def test_ocr_without_a_describer_returns_nothing(tmp_path: Path) -> None:
    parser = PyMuPDFParser(enable_ocr=True)

    document = await parser.parse(_scanned_pdf(tmp_path / "scan.pdf"))

    assert document.pages[0].content == ""
