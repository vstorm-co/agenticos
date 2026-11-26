"""The Docling parser: resuming a stored task, and how a refusal ends a document."""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, asyncpg

from app.db.models.rag_document import RAGDocument
from app.repositories import rag_document as rag_document_repo
from app.services.rag.config import PdfParser, RAGSettings
from app.services.rag.docling import (
    PAGE_BREAK,
    DoclingParser,
    DoclingRefused,
    DoclingUnavailable,
    ParserTask,
)
from app.services.rag.documents import PdfParserFactory
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionStatus

pytestmark = pytest.mark.anyio

_BASE = "http://docling.internal:5001"
_CONNECTION = uuid4()


class _Store:
    """An in-memory `ParserTaskStore`."""

    def __init__(self, stored: ParserTask | None = None, *, fenced: bool = False) -> None:
        self.stored = stored
        self.fenced = fenced
        self.saves: list[ParserTask] = []
        self.clears = 0

    async def load(self) -> ParserTask | None:
        return self.stored

    async def save(self, task: ParserTask) -> bool:
        self.saves.append(task)
        if self.fenced:
            return False
        self.stored = task
        return True

    async def clear(self) -> bool:
        self.clears += 1
        if self.fenced:
            return False
        self.stored = None
        return True


class _Server:
    """A Docling Serve that records its calls and answers each poll in turn."""

    def __init__(
        self,
        *,
        polls: list[tuple[int, dict[str, Any]]] | None = None,
        result: tuple[int, dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.polls = list(polls or [(200, {"task_status": "success"})])
        self.result = result or (
            200,
            {
                "status": "success",
                "document": {
                    "md_content": "hello",
                    "json_content": {"texts": [{"prov": [{"page_no": 1}]}]},
                },
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": f"new-{len(self.calls)}"})
        if "/status/" in request.url.path:
            status, body = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
            return httpx.Response(status, json=body)
        status, body = self.result
        return httpx.Response(status, json=body)

    @property
    def posts(self) -> int:
        return sum(1 for method, _ in self.calls if method == "POST")


def _parser(server: _Server, store: _Store | None, *, timeout: float = 600.0) -> DoclingParser:
    settings = RAGSettings(
        pdf_parser=PdfParser(
            method="docling",
            docling_connection_id=_CONNECTION,
            docling_base_url=_BASE,
            docling_api_key="sekret",
            liteparse_timeout_seconds=timeout,
        )
    )
    built = PdfParserFactory.create("docling", settings, task_store=store)
    assert isinstance(built, DoclingParser)
    return DoclingParser(built.target, built.options, store, client=server.client())


def _pdf(tmp_path: Path, content: bytes = b"%PDF-1") -> Path:
    path = tmp_path / "a.pdf"
    path.write_bytes(content)
    return path


async def test_fresh_parse_submits_and_stores_task(tmp_path: Path) -> None:
    server, store = _Server(), _Store()

    document = await _parser(server, store).parse(_pdf(tmp_path))

    assert server.posts == 1
    assert [p.content for p in document.pages] == ["hello"]
    assert len(store.saves) == 1
    saved = store.saves[0]
    assert saved["provider"] == "docling" and saved["task_id"].startswith("new-")
    assert "sekret" not in str(saved)


async def test_retry_resumes_stored_task_without_submitting(tmp_path: Path) -> None:
    path = _pdf(tmp_path)
    first = _Server(polls=[(503, {})])
    store = _Store()
    with pytest.raises(DoclingUnavailable):
        await _parser(first, store).parse(path)
    assert store.stored is not None

    second = _Server()
    document = await _parser(second, store).parse(path)

    assert second.posts == 0
    assert (("GET", f"/v1/result/{store.saves[0]['task_id']}")) in second.calls
    assert document.pages[0].content == "hello"
    assert store.stored is None


async def test_changed_settings_submit_new_task(tmp_path: Path) -> None:
    path = _pdf(tmp_path)
    store = _Store()
    await _parser(_Server(), store).parse(path)
    stale = store.saves[0]
    store.stored = {**stale, "fingerprint": "from-other-settings"}
    server = _Server()

    await _parser(server, store).parse(path)

    assert server.posts == 1


async def test_changed_file_submits_new_task(tmp_path: Path) -> None:
    store = _Store()
    await _parser(_Server(), store).parse(_pdf(tmp_path))
    store.stored = store.saves[0]
    server = _Server()

    await _parser(server, store).parse(_pdf(tmp_path, b"%PDF-2"))

    assert server.posts == 1


async def test_task_gone_resubmits_once(tmp_path: Path) -> None:
    path = _pdf(tmp_path)
    store = _Store()
    first = _Server()
    await _parser(first, store).parse(path)
    store.stored = store.saves[0]
    server = _Server(polls=[(404, {}), (200, {"task_status": "success"})])

    document = await _parser(server, store).parse(path)

    assert server.posts == 1
    assert document.pages[0].content == "hello"
    assert store.saves[-1]["task_id"].startswith("new-")


async def test_task_gone_twice_is_unavailable(tmp_path: Path) -> None:
    store = _Store()
    server = _Server(polls=[(404, {})])

    with pytest.raises(DoclingUnavailable):
        await _parser(server, store).parse(_pdf(tmp_path))

    assert server.posts == 2


async def test_success_clears_stored_task(tmp_path: Path) -> None:
    store = _Store()

    await _parser(_Server(), store).parse(_pdf(tmp_path))

    assert store.clears == 1 and store.stored is None


async def test_definitive_refusal_clears_task(tmp_path: Path) -> None:
    store = _Store()
    server = _Server(result=(200, {"status": "failure", "errors": []}))

    with pytest.raises(DoclingRefused):
        await _parser(server, store).parse(_pdf(tmp_path))

    assert store.clears == 1 and store.stored is None


async def test_deadline_keeps_task(tmp_path: Path) -> None:
    store = _Store()
    server = _Server(polls=[(200, {"task_status": "pending"})])

    with pytest.raises(DoclingRefused) as raised:
        await _parser(server, store, timeout=0.0001).parse(_pdf(tmp_path))

    assert raised.value.details == {"provider": "docling", "keep_task": True}
    assert store.clears == 0 and store.stored is not None


async def test_unavailable_keeps_task(tmp_path: Path) -> None:
    store = _Store()
    server = _Server(polls=[(503, {})])

    with pytest.raises(DoclingUnavailable):
        await _parser(server, store).parse(_pdf(tmp_path))

    assert store.clears == 0 and store.stored is not None


async def test_without_store_still_parses(tmp_path: Path) -> None:
    server = _Server(polls=[(404, {}), (200, {"task_status": "success"})])

    document = await _parser(server, None).parse(_pdf(tmp_path))

    assert document.pages[0].content == "hello" and server.posts == 2


async def test_without_store_a_refusal_just_raises(tmp_path: Path) -> None:
    server = _Server(result=(200, {"status": "failure"}))

    with pytest.raises(DoclingRefused):
        await _parser(server, None).parse(_pdf(tmp_path))


async def test_a_fenced_store_does_not_stop_the_parse(tmp_path: Path) -> None:
    store = _Store(fenced=True)

    document = await _parser(_Server(), store).parse(_pdf(tmp_path))

    assert document.pages[0].content == "hello" and store.clears == 1


async def test_an_extension_it_does_not_claim_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.mp3"
    path.write_bytes(b"x")

    with pytest.raises(ValueError, match="not supported by Docling"):
        await _parser(_Server(), None).parse(path)


async def test_the_parser_owns_its_client_when_given_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _Server()
    parser = _parser(server, None)
    parser._client = None
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(server._handle), **kwargs),
    )

    document = await parser.parse(_pdf(tmp_path))

    assert document.pages[0].content == "hello"


@pytest.mark.security
async def test_the_key_is_not_in_the_fingerprint(tmp_path: Path) -> None:
    path = _pdf(tmp_path)
    one, two = _Store(), _Store()
    await _parser(_Server(), one).parse(path)
    parser = _parser(_Server(), two)
    object.__setattr__(parser.target, "api_key", "a-different-key")
    await parser.parse(path)

    assert one.saves[0]["fingerprint"] == two.saves[0]["fingerprint"]


def test_factory_builds_docling_parser() -> None:
    settings = RAGSettings(
        enable_ocr=True,
        pdf_parser=PdfParser(
            method="docling",
            docling_connection_id=_CONNECTION,
            docling_base_url=_BASE,
            docling_api_key="",
            docling_ocr_languages=["de"],
            docling_ocr_preset="rapidocr",
            docling_table_mode="fast",
            liteparse_auto_ocr=False,
            liteparse_max_pages=12,
            liteparse_timeout_seconds=90.0,
        ),
    )

    built = PdfParserFactory.create("docling", settings)

    assert isinstance(built, DoclingParser)
    assert built.target.api_key is None and built.target.base_url == _BASE
    assert built.options.force_ocr and built.options.do_ocr
    assert built.options.ocr_languages == ("de",) and built.options.max_pages == 12
    assert ("table_mode", "fast") in built.options.form()
    assert ("document_timeout", "90") in built.options.form()


def test_factory_needs_the_connection() -> None:
    with pytest.raises(ValueError, match="Docling needs"):
        PdfParserFactory.create("docling", RAGSettings())
    with pytest.raises(ValueError, match="Docling needs"):
        PdfParserFactory.create("docling", None)


def test_ocr_off_never_forces_ocr() -> None:
    settings = RAGSettings(
        enable_ocr=False,
        pdf_parser=PdfParser(method="docling", docling_base_url=_BASE, liteparse_auto_ocr=False),
    )

    built = PdfParserFactory.create("docling", settings)

    assert isinstance(built, DoclingParser) and not built.options.force_ocr


async def test_docling_refusal_fails_document_without_retry(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    processor = MagicMock(
        process_file=AsyncMock(side_effect=DoclingRefused("Docling could not read pages 2."))
    )
    service = IngestionService(processor=processor, vector_store=MagicMock())

    with caplog.at_level(logging.WARNING, logger="app.services.rag.ingestion"):
        result = await service.ingest_file(filepath=_pdf(tmp_path), collection_name="kb")

    assert result.status is IngestionStatus.ERROR and result.refused
    assert result.error_message == "Docling could not read pages 2."
    assert all(r.exc_info is None for r in caplog.records)


async def test_docling_unavailable_raises_for_retry(tmp_path: Path) -> None:
    processor = MagicMock(process_file=AsyncMock(side_effect=DoclingUnavailable("later")))
    service = IngestionService(processor=processor, vector_store=MagicMock())

    result = await service.ingest_file(filepath=_pdf(tmp_path), collection_name="kb")

    assert result.status is IngestionStatus.ERROR and not result.refused
    assert result.error_message == "later"


async def test_parser_task_write_is_fenced_by_attempt() -> None:
    db = MagicMock(execute=AsyncMock(return_value=MagicMock(rowcount=0)), flush=AsyncMock())
    doc_id = uuid4()

    written = await rag_document_repo.set_parser_task(
        db, doc_id, parser_task={"task_id": "t"}, expected_attempt=7
    )

    assert written is False
    compiled = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "rag_documents.id = %(id_1)s" in sql
    assert "rag_documents.ingestion_attempt = %(ingestion_attempt_1)s" in sql
    assert "!=" not in sql and "<>" not in sql
    assert compiled.params["id_1"] == doc_id
    assert compiled.params["ingestion_attempt_1"] == 7
    assert compiled.params["parser_task"] == {"task_id": "t"}
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    assert await rag_document_repo.set_parser_task(
        db, uuid4(), parser_task=None, expected_attempt=1
    )


async def test_the_service_passes_the_attempt_to_the_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.rag_document import RAGDocumentService

    setter = AsyncMock(return_value=True)
    monkeypatch.setattr(rag_document_repo, "set_parser_task", setter)
    doc_id = uuid4()

    assert await RAGDocumentService(MagicMock()).record_parser_task(
        str(doc_id), {"task_id": "t"}, attempt=3
    )

    setter.assert_awaited_once()
    assert setter.await_args.args[1] == doc_id
    assert setter.await_args.kwargs == {"parser_task": {"task_id": "t"}, "expected_attempt": 3}


class TestTheWorkersStore:
    """`_DocumentParserTasks`: the row a retry finds the task on."""

    @staticmethod
    def _patch(monkeypatch: pytest.MonkeyPatch, service: MagicMock) -> None:
        from contextlib import asynccontextmanager

        from app.worker.tasks import rag_tasks

        @asynccontextmanager
        async def session() -> Any:
            yield MagicMock()

        monkeypatch.setattr(rag_tasks, "get_worker_db_context", session)
        monkeypatch.setattr("app.services.rag_document.RAGDocumentService", lambda db: service)

    async def test_save_and_clear_write_for_the_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.worker.tasks.rag_tasks import _DocumentParserTasks

        service = MagicMock(record_parser_task=AsyncMock(return_value=True))
        self._patch(monkeypatch, service)
        store = _DocumentParserTasks("doc-1", 4)
        task: ParserTask = {
            "provider": "docling",
            "task_id": "t",
            "fingerprint": "f",
            "submitted_at": "s",
        }

        assert await store.save(task) and await store.clear()

        calls = service.record_parser_task.await_args_list
        assert calls[0].args == ("doc-1", dict(task)) and calls[0].kwargs == {"attempt": 4}
        assert calls[1].args == ("doc-1", None)

    async def test_load_reads_the_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core.exceptions import NotFoundError
        from app.worker.tasks.rag_tasks import _DocumentParserTasks

        stored = {"provider": "docling", "task_id": "t", "fingerprint": "f", "submitted_at": "s"}
        get = AsyncMock(
            side_effect=[
                MagicMock(parser_task=stored),
                MagicMock(parser_task=None),
                NotFoundError(message="gone"),
            ]
        )
        self._patch(monkeypatch, MagicMock(get_document=get))
        store = _DocumentParserTasks("doc-1", 1)

        assert await store.load() == stored
        assert await store.load() is None
        assert await store.load() is None


async def test_docling_pages_reach_the_chunker(tmp_path: Path) -> None:
    """The marker never survives into a page, and numbering follows Docling's pages."""
    body = {
        "status": "success",
        "document": {
            "md_content": f"one{PAGE_BREAK}two",
            "json_content": {"texts": [{"prov": [{"page_no": 2}]}, {"prov": [{"page_no": 5}]}]},
        },
    }
    server = _Server(result=(200, body))

    document = await _parser(server, None).parse(_pdf(tmp_path))

    assert [(p.page_num, p.content) for p in document.pages] == [(2, "one"), (5, "two")]


async def test_the_deadline_only_offers_a_retry_when_a_task_is_kept(tmp_path: Path) -> None:
    pending = [(200, {"task_status": "pending"})]
    with pytest.raises(DoclingRefused) as kept:
        await _parser(_Server(polls=pending), _Store(), timeout=0.0001).parse(_pdf(tmp_path))
    with pytest.raises(DoclingRefused) as lost:
        await _parser(_Server(polls=pending), None, timeout=0.0001).parse(_pdf(tmp_path))

    assert "Retry the document" in kept.value.message
    assert "Retry the document" not in lost.value.message


async def test_a_cleared_task_is_stored_as_sql_null() -> None:
    """Cleared means no row value at all, not the JSON document `null`.

    `parser_task IS NULL` is how a person (or a report) asks which documents still
    wait on a conversion; a JSON `null` answers that question wrong.
    """
    dialect = asyncpg.dialect()  # the driver the application runs on
    stored = RAGDocument.__table__.c.parser_task.type.bind_processor(dialect)
    plain = JSONB().bind_processor(dialect)

    # What the UPDATE sends for a cleared task: SQL NULL, where a plain JSONB
    # column sends the JSON text `null` - the defect this pins.
    assert stored(None) is None
    assert plain(None) == "null"


async def test_a_heading_with_no_text_adds_no_stray_marker(tmp_path: Path) -> None:
    import docx

    from app.services.rag.documents import DocxDocumentParser

    word = docx.Document()
    word.add_heading("", 1)
    word.add_paragraph("Body")
    path = tmp_path / "empty-heading.docx"
    word.save(path)

    document = await DocxDocumentParser().parse(path)

    assert document.pages[0].content == "Body"
