"""Semantic work budgets for attacker-controlled PyMuPDF documents."""

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from app.services.rag.config import RAGSettings
from app.services.rag.documents import DocumentLimitExceeded, DocumentProcessor, PyMuPDFParser

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _pdf(path: Path, pages: int) -> Path:
    with pymupdf.open() as document:
        for _ in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), "ordinary text")
        document.save(path)
    return path


async def test_page_budget_is_checked_before_any_page_text_is_scanned(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "many-pages.pdf", 2)
    parser = PyMuPDFParser(max_pages=1)

    with (
        patch.object(pymupdf.Page, "get_text", autospec=True) as get_text,
        pytest.raises(DocumentLimitExceeded) as caught,
    ):
        await parser.parse(path)

    assert caught.value.budget == "pages"
    assert caught.value.maximum == 1
    get_text.assert_not_called()


async def test_extracted_content_stops_before_an_over_budget_page_is_retained(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dense.pdf"
    path.write_bytes(b"pdf")
    page = SimpleNamespace(
        number=0,
        get_text=lambda _format: [(0, 0, 10, 10, "too much text", 0, 0)],
        find_tables=lambda: None,
    )
    document = MagicMock()
    document.__enter__.return_value = document
    document.__exit__.return_value = None
    document.__len__.return_value = 1
    document.__iter__.return_value = iter([page])
    document.metadata = {}
    document.get_toc.return_value = []

    with (
        patch("pymupdf.open", return_value=document),
        pytest.raises(DocumentLimitExceeded) as caught,
    ):
        await PyMuPDFParser(max_content_chars=4).parse(path)

    assert caught.value.budget == "extracted characters"
    assert caught.value.maximum == 4


def test_table_count_is_refused_before_tables_are_materialized() -> None:
    table = SimpleNamespace(to_pandas=MagicMock())
    page = SimpleNamespace(find_tables=lambda: SimpleNamespace(tables=[table, table]))
    parser = PyMuPDFParser(max_tables=1)

    with pytest.raises(DocumentLimitExceeded) as caught:
        parser._extract_tables(
            page,
            remaining_tables=1,
            remaining_chars=100,
            deadline=time.monotonic() + 1,
        )

    assert caught.value.budget == "tables"
    table.to_pandas.assert_not_called()


async def test_elapsed_budget_is_checked_before_document_metadata_expansion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "slow.pdf"
    path.write_bytes(b"pdf")
    document = MagicMock()
    document.__enter__.return_value = document
    document.__exit__.return_value = None
    document.__len__.return_value = 1

    with (
        patch("pymupdf.open", return_value=document),
        patch("app.services.rag.documents.time.monotonic", side_effect=[0.0, 2.0]),
        pytest.raises(DocumentLimitExceeded) as caught,
    ):
        await PyMuPDFParser(timeout_seconds=1.0).parse(path)

    assert caught.value.budget == "elapsed seconds"
    assert caught.value.maximum == 1.0
    document.get_toc.assert_not_called()


async def test_prepared_chunks_cannot_amplify_bounded_extracted_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dense.txt"
    path.write_text("one two three four", encoding="utf-8")
    processor = DocumentProcessor(RAGSettings(chunk_size=8, chunk_overlap=7, max_chunk_chars=10))

    with pytest.raises(DocumentLimitExceeded) as caught:
        await processor.process_file(path)

    assert caught.value.budget == "prepared chunk characters"
    assert caught.value.maximum == 10
