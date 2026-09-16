"""The document and OCR services' parsing stage.

The engines are the ingestion pipeline's and are tested with it; what is new
here is running them for a caller who named no collection. So these cover the
boundary: which parsers may be named, which file types each accepts, what a
document that yields nothing answers, and that the temporary directory the
bytes were written to is gone whichever way the call ended.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pymupdf
import pytest

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.ml import parsing
from app.services.rag.models import Document, DocumentMetadata, DocumentPage, DocumentPageChunk

pytestmark = pytest.mark.anyio

_PROCESS = "app.services.ml.parsing.DocumentProcessor.process_file"


def _pdf(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    return bytes(document.tobytes())


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put the call's scratch directory somewhere the test can look for it."""
    made = tmp_path / "ml-parse-probe"

    def mkdtemp(prefix: str) -> str:
        del prefix
        made.mkdir()
        return str(made)

    monkeypatch.setattr(parsing.tempfile, "mkdtemp", mkdtemp)
    return made


def _parsed(pages: int = 1) -> Document:
    document = Document(
        pages=[DocumentPage(page_num=index + 1, content="recognised") for index in range(pages)],
        metadata=DocumentMetadata(
            filename="document.pdf",
            filesize=8,
            filetype="pdf",
            source_path="document.pdf",
            content_hash="abc",
        ),
    )
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content="recognised",
            chunk_num=0,
            parent_doc_id=document.id,
            page_num=1,
            content="recognised",
        )
    ]
    return document


async def test_a_pdf_is_read_into_pages_and_chunks() -> None:
    result = await parsing.analyze(_pdf("hello from a page"), "notes.pdf", parser="pymupdf")

    assert result.filetype == "pdf"
    assert [page.page_num for page in result.pages] == [1]
    assert "hello from a page" in result.pages[0].content
    assert result.chunks
    assert len(result.content_hash) == 64


async def test_the_byte_count_answers_for_what_was_submitted() -> None:
    content = _pdf("x")
    result = await parsing.analyze(content, "notes.pdf", parser="pymupdf")

    assert result.byte_size == len(content)


async def test_a_parser_this_service_does_not_offer_is_refused_on_the_field() -> None:
    with pytest.raises(BadRequestError) as caught:
        await parsing.analyze(b"", "notes.pdf", parser="llamaparse")

    assert caught.value.details is not None
    assert caught.value.details["fields"][0]["field"] == "parser"


async def test_a_file_type_the_chosen_parser_cannot_read_is_refused() -> None:
    with pytest.raises(BadRequestError) as caught:
        await parsing.analyze(b"", "sheet.xlsx", parser="pymupdf")

    assert caught.value.details is not None
    assert caught.value.details["fields"][0]["field"] == "file"


async def test_a_file_with_no_extension_is_refused_and_said_so() -> None:
    with pytest.raises(BadRequestError) as caught:
        await parsing.analyze(b"", "scan", parser="pymupdf")

    assert "no extension" in caught.value.details["fields"][0]["message"]


async def test_a_document_that_yields_nothing_points_at_the_ocr_service() -> None:
    with (
        patch(_PROCESS, new=AsyncMock(side_effect=ValueError("no indexable text"))),
        pytest.raises(BadRequestError) as caught,
    ):
        await parsing.analyze(_pdf(""), "scan.pdf", parser="pymupdf")

    assert "OCR service" in caught.value.message


async def test_an_engine_failure_names_the_stage_and_keeps_its_own_words_out() -> None:
    """The parser's message carries a scratch path and the engine's own text."""
    engine_said = RuntimeError("scratch/ml-parse-x: boom")
    with (
        patch(_PROCESS, new=AsyncMock(side_effect=engine_said)),
        pytest.raises(ExternalServiceError) as caught,
    ):
        await parsing.analyze(_pdf("x"), "scan.pdf", parser="pymupdf")

    assert caught.value.details == {"filename": "scan.pdf", "parser": "pymupdf", "stage": "parse"}
    assert "boom" not in caught.value.message


async def test_recognition_is_configured_with_the_language_and_the_server_it_was_given() -> None:
    built: list[object] = []

    class _Recording:
        def __init__(self, settings: object) -> None:
            built.append(settings)

        async def process_file(self, path: Path) -> Document:
            del path
            return _parsed()

    with patch("app.services.ml.parsing.DocumentProcessor", _Recording):
        await parsing.recognise(
            b"%PDF-1.4", "scan.pdf", language="pol", ocr_server_url="http://ocr:8000"
        )

    settings = built[0]
    assert settings.enable_ocr is True
    assert settings.pdf_parser.liteparse_auto_ocr is False
    assert settings.pdf_parser.liteparse_ocr_language == "pol"
    assert settings.pdf_parser.liteparse_ocr_server_url == "http://ocr:8000"


async def test_recognition_refuses_a_file_that_has_no_pages_to_look_at() -> None:
    """Handing back a text file's own characters is not recognition."""
    with pytest.raises(BadRequestError) as caught:
        await parsing.recognise(b"hello", "notes.txt")

    assert caught.value.details["fields"][0]["field"] == "file"


async def test_the_scratch_directory_is_gone_once_the_call_has_answered(
    scratch: Path,
) -> None:
    await parsing.analyze(_pdf("x"), "notes.pdf", parser="pymupdf")

    assert not scratch.exists()


async def test_the_scratch_directory_is_gone_even_when_the_parse_failed(
    scratch: Path,
) -> None:
    """The removal is in a `finally`, which is the only reason this holds."""
    with (
        patch(_PROCESS, new=AsyncMock(side_effect=RuntimeError("boom"))),
        pytest.raises(ExternalServiceError),
    ):
        await parsing.analyze(_pdf("x"), "notes.pdf", parser="pymupdf")

    assert not scratch.exists()


async def test_the_chunking_strategy_a_caller_names_is_the_one_used() -> None:
    built: list[object] = []

    class _Recording:
        def __init__(self, settings: object) -> None:
            built.append(settings)

        async def process_file(self, path: Path) -> Document:
            del path
            return _parsed()

    with patch("app.services.ml.parsing.DocumentProcessor", _Recording):
        await parsing.analyze(
            b"%PDF-1.4",
            "notes.pdf",
            parser="pymupdf",
            chunk_size=900,
            chunk_overlap=90,
            chunking_strategy="markdown",
        )

    assert built[0].chunk_size == 900
    assert built[0].chunk_overlap == 90
    assert built[0].chunking_strategy == "markdown"
