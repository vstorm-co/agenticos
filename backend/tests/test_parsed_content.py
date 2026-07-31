"""What the parsed-content view answers with, and when it refuses.

The chunks in the vector store are the only record of what a parser produced,
so `GET /kb/{kb_id}/documents/{doc_id}/parsed` reads them back rather than
re-parsing. Two things here are worth pinning explicitly:

*The empty-parse case.* Markdown reconstruction wraps an unreadable scan in an
empty fenced block - ``"```text\\n\\n```"` - which `.strip()`` keeps, so a
document that parsed to nothing looks non-empty to the naive check. The service
answers with `has_indexable_text`, and these tests are what fail if somebody
"simplifies" that back to a strip.

*The refusal.* A document still processing, or one whose ingestion failed, has
no parse to show; answering an empty page list for it would be indistinguishable
from a real empty parse.

`app/services/rag/*` is template-inherited and outside the coverage gate,
which is exactly why this behaviour is pinned by name rather than left to a
percentage - see `tests/test_supported_formats.py` for the precedent.
"""

import uuid
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.rag_document import RAGDocument
from app.repositories import rag_document_repo
from app.schemas.rag import RAGParsedContent
from app.services.rag.models import DocumentChunk
from app.services.rag.vectorstore import BaseVectorStore
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio

UNREADABLE_SCAN = "```text\n\n```"


def _doc(
    *,
    status: str = "done",
    vector_document_id: str | None = "vec-doc-1",
    ingestion_config: dict[str, object] | None = None,
) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        collection_name="docs",
        filename="report.pdf",
        filesize=1024,
        filetype="pdf",
        status=status,
        vector_document_id=vector_document_id,
        ingestion_config=ingestion_config if ingestion_config is not None else {},
    )


class _StoreWith:
    """A vector store holding one document's chunks, and nothing else."""

    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = chunks
        self.asked_for: tuple[str, str] | None = None

    async def get_document_chunks(
        self, collection_name: str, document_id: str
    ) -> list[DocumentChunk]:
        self.asked_for = (collection_name, document_id)
        return self.chunks


async def _parsed(
    monkeypatch: pytest.MonkeyPatch, doc: RAGDocument, store: _StoreWith
) -> RAGParsedContent:
    """Run the service over one stored document and one fake store."""

    async def get_by_id(db: AsyncSession, doc_id: uuid.UUID) -> RAGDocument:
        return doc

    monkeypatch.setattr(rag_document_repo, "get_by_id", get_by_id)
    service = RAGDocumentService(db=cast(AsyncSession, None))
    return await service.get_parsed_content(str(doc.id), cast(BaseVectorStore, store))


async def test_chunks_come_back_grouped_by_page_in_document_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = _doc(ingestion_config={"pdf_parser": "pymupdf"})
    store = _StoreWith(
        [
            DocumentChunk(content="# Page one, first", page_num=1, chunk_num=0),
            DocumentChunk(content="Page one, second", page_num=1, chunk_num=1),
            DocumentChunk(content="Page two", page_num=2, chunk_num=0),
        ]
    )

    parsed = await _parsed(monkeypatch, doc, store)

    assert store.asked_for == ("docs", "vec-doc-1")
    assert parsed.parser == "pymupdf"
    assert parsed.chunk_count == 3
    assert parsed.has_text is True
    assert [(page.page_num, page.chunks) for page in parsed.pages] == [
        (1, ["# Page one, first", "Page one, second"]),
        (2, ["Page two"]),
    ]


async def test_a_page_of_markdown_scaffolding_is_reported_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty fenced block is an unreadable scan, not content.

    It is not whitespace, so a `.strip()` check would call the page fine and
    the UI would render a blank code block with no explanation.
    """
    doc = _doc()
    store = _StoreWith(
        [
            DocumentChunk(content=UNREADABLE_SCAN, page_num=1, chunk_num=0),
            DocumentChunk(content="Real text on page two.", page_num=2, chunk_num=0),
        ]
    )

    parsed = await _parsed(monkeypatch, doc, store)

    assert parsed.has_text is True
    assert parsed.pages[0].has_text is False
    assert parsed.pages[1].has_text is True


async def test_a_document_that_parsed_to_nothing_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every page scaffolding means the whole document reports no text.

    This is the state the UI must surface distinctly: afterwards it is the only
    way to tell "ingested fine, never matches" from "nothing readable came out".
    """
    doc = _doc()
    store = _StoreWith([DocumentChunk(content=UNREADABLE_SCAN, page_num=1, chunk_num=0)])

    parsed = await _parsed(monkeypatch, doc, store)

    assert parsed.has_text is False
    assert parsed.chunk_count == 1


async def test_a_document_still_processing_has_no_parsed_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = _doc(status="processing", vector_document_id=None)

    with pytest.raises(NotFoundError):
        await _parsed(monkeypatch, doc, _StoreWith([]))


async def test_a_failed_ingestion_has_no_parsed_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc = _doc(status="error", vector_document_id=None)

    with pytest.raises(NotFoundError):
        await _parsed(monkeypatch, doc, _StoreWith([]))


async def test_a_done_document_whose_vectors_are_gone_answers_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vectors dropped out of band are an empty answer, not a 500.

    The tracked row and the vector table can disagree - a collection dropped
    through `/rag` leaves rows behind until cleanup runs - and the honest
    answer for the viewer is "nothing indexed", rendered as the empty state.
    """
    doc = _doc()
    store = _StoreWith([])

    parsed = await _parsed(monkeypatch, doc, store)

    assert parsed.pages == []
    assert parsed.has_text is False
    assert parsed.chunk_count == 0


async def test_a_document_ingested_before_provenance_reports_no_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty stored configuration answers `None`, the same truth the
    document listing tells: nobody wrote down what read it."""
    doc = _doc(ingestion_config={})
    store = _StoreWith([DocumentChunk(content="Text.", page_num=1, chunk_num=0)])

    parsed = await _parsed(monkeypatch, doc, store)

    assert parsed.parser is None
