"""Operator confirmation is deliberate, and ingestion stamps a trusted origin."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from click.testing import CliRunner

from app.commands import rag
from app.core.exceptions import BadRequestError
from app.db.vector_tables import VectorWriterKind
from app.repositories.rag_document import UnfiledProvenanceCounts
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import Document, DocumentMetadata, DocumentPage, DocumentPageChunk


@pytest.mark.parametrize("args", [[], ["--confirm-operator", "--yes"], ["--confirm-operator"]])
def test_confirmation_is_explicit_and_success_follows_commit(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    committed = False

    @asynccontextmanager
    async def context() -> AsyncIterator[MagicMock]:
        nonlocal committed
        yield MagicMock()
        committed = True

    service = MagicMock(
        confirm_operator_unfiled=AsyncMock(return_value=2),
        audit_unfiled_provenance=AsyncMock(return_value=UnfiledProvenanceCounts(2, 1, 0, 0)),
    )
    monkeypatch.setattr(rag, "get_db_context", context)
    monkeypatch.setattr(rag, "RAGDocumentService", MagicMock(return_value=service))
    original_success = rag.success

    def success(message: str) -> None:
        assert committed
        original_success(message)

    monkeypatch.setattr(rag, "success", success)
    result = CliRunner().invoke(rag.rag_unfiled_provenance, ["manuals", *args], input="y\n")
    assert result.exit_code == 0, result.output
    assert '"document": 1' in result.output
    assert committed
    if args:
        service.confirm_operator_unfiled.assert_awaited_once_with("manuals")
        assert "Confirmed 2" in result.output
    else:
        service.confirm_operator_unfiled.assert_not_awaited()


def test_refusing_the_prompt_does_not_touch_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database = MagicMock(side_effect=AssertionError("must not open"))
    monkeypatch.setattr(rag, "get_db_context", database)
    result = CliRunner().invoke(
        rag.rag_unfiled_provenance, ["manuals", "--confirm-operator"], input="n\n"
    )
    assert result.exit_code != 0
    database.assert_not_called()


def test_invalid_destination_fails_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rag,
        "_unfiled_provenance",
        AsyncMock(side_effect=BadRequestError(message="Invalid collection")),
    )
    result = CliRunner().invoke(rag.rag_unfiled_provenance, ["documents"])
    assert result.exit_code == 1
    assert "Invalid collection" in result.output


@pytest.mark.anyio
@pytest.mark.parametrize("origin", [VectorWriterKind.DOCUMENT, VectorWriterKind.OPERATOR])
async def test_ingester_overwrites_parser_origin(origin: VectorWriterKind) -> None:
    document = Document(
        pages=[DocumentPage(page_num=1, content="body")],
        metadata=DocumentMetadata(
            filename="test.txt", filesize=4, filetype="txt", writer_kind=VectorWriterKind.OPERATOR
        ),
    )
    document.chunked_pages = [
        DocumentPageChunk(
            page_num=1, chunk_content="body", parent_doc_id=document.id, content="body"
        )
    ]
    processor = MagicMock(process_file=AsyncMock(return_value=document))
    store = MagicMock(insert_document=AsyncMock())
    service = IngestionService(processor, store, writer_kind=origin)
    await service.ingest_file(Path("test.txt"), "manuals", replace=False)
    store.insert_document.assert_awaited_once()
    assert document.metadata.writer_kind is origin
    assert "writer_kind" not in document.metadata.model_dump()
