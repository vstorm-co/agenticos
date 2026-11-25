"""The document and OCR services' parsing stage.

The engines are the ingestion pipeline's and are tested with it; what is new
here is running them for a caller who named no collection. So these cover the
boundary: which parsers may be named, which file types each accepts, what a
document that yields nothing answers, and that the temporary directory the
bytes were written to is gone whichever way the call ended.
"""

import asyncio
import contextlib
import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import pymupdf
import pytest

from app.core.exceptions import BadRequestError, ExternalServiceError, RateLimitError
from app.services.ml import parsing
from app.services.rag.documents import DocumentLimitExceeded
from app.services.rag.models import Document, DocumentMetadata, DocumentPage, DocumentPageChunk

pytestmark = pytest.mark.anyio

_PARSE = "app.services.ml.parsing._parse_in_child"


class _FakeWriter:
    def __init__(self) -> None:
        self.written = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeReader:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = list(chunks or [])

    async def read(self, _size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: list[bytes] | None = None,
        stderr: list[bytes] | None = None,
        returncode: int = 0,
    ) -> None:
        self.pid = 12345
        self.stdin = _FakeWriter()
        self.stdout = _FakeReader(stdout)
        self.stderr = _FakeReader(stderr)
        self.returncode: int | None = returncode

    async def wait(self) -> int:
        assert self.returncode is not None
        return self.returncode


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
        patch(_PARSE, new=AsyncMock(side_effect=ValueError("no indexable text"))),
        pytest.raises(BadRequestError) as caught,
    ):
        await parsing.analyze(_pdf(""), "scan.pdf", parser="pymupdf")

    assert "OCR service" in caught.value.message


async def test_an_engine_failure_names_the_stage_and_keeps_its_own_words_out() -> None:
    """The parser's message carries a scratch path and the engine's own text."""
    engine_said = RuntimeError("scratch/ml-parse-x: boom")
    with (
        patch(_PARSE, new=AsyncMock(side_effect=engine_said)),
        pytest.raises(ExternalServiceError) as caught,
    ):
        await parsing.analyze(_pdf("x"), "scan.pdf", parser="pymupdf")

    assert caught.value.details == {"filename": "scan.pdf", "parser": "pymupdf", "stage": "parse"}
    assert "boom" not in caught.value.message


async def test_recognition_is_configured_with_the_language_and_the_server_it_was_given() -> None:
    built: list[object] = []

    async def record(settings: object, path: Path) -> Document:
        del path
        built.append(settings)
        return _parsed()

    with patch(_PARSE, new=record):
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
        patch(_PARSE, new=AsyncMock(side_effect=RuntimeError("boom"))),
        pytest.raises(ExternalServiceError),
    ):
        await parsing.analyze(_pdf("x"), "notes.pdf", parser="pymupdf")

    assert not scratch.exists()


async def test_the_chunking_strategy_a_caller_names_is_the_one_used() -> None:
    built: list[object] = []

    async def record(settings: object, path: Path) -> Document:
        del path
        built.append(settings)
        return _parsed()

    with patch(_PARSE, new=record):
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


async def test_an_overlap_at_or_above_the_chunk_is_refused() -> None:
    """The splitter accepts it and the document comes back multiplied.

    An overlap equal to the chunk advances by about one separator per chunk while
    keeping an almost complete copy of the last one, so a legal upload answers
    with hundreds of megabytes. `IngestionConfig` refuses the same shape.
    """
    with pytest.raises(BadRequestError) as caught:
        await parsing.analyze(
            _pdf("x"), "notes.pdf", parser="pymupdf", chunk_size=512, chunk_overlap=512
        )

    assert caught.value.details["fields"][0]["field"] == "chunk_overlap"


async def test_recognition_refuses_a_docx_rather_than_reading_its_paragraphs() -> None:
    """The pipeline routes `.docx` natively, so OCR here would silently skip its scans."""
    with pytest.raises(BadRequestError) as caught:
        await parsing.recognise(b"PK", "scan.docx")

    assert caught.value.details["fields"][0]["field"] == "file"


def test_the_recognisable_formats_exclude_everything_routed_natively() -> None:
    assert parsing.RECOGNISABLE_FORMATS.isdisjoint({".txt", ".md", ".docx"})
    assert ".pdf" in parsing.RECOGNISABLE_FORMATS


async def test_a_malformed_file_is_the_callers_problem_not_a_500() -> None:
    """`python-docx` raises neither ValueError nor RuntimeError on a file that is not a zip."""

    class NotAZip(Exception):
        pass

    with (
        patch(_PARSE, new=AsyncMock(side_effect=NotAZip("package not found"))),
        pytest.raises(BadRequestError) as caught,
    ):
        await parsing.analyze(_pdf("x"), "notes.pdf", parser="pymupdf")

    assert caught.value.details["stage"] == "parse"
    assert "package not found" not in caught.value.message


async def test_recognition_bounds_the_pages_and_the_deadline_it_will_spend() -> None:
    """Ingestion's thousand pages and ten minutes are wrong for a synchronous call."""
    built: list[object] = []

    async def record(settings: object, path: Path) -> Document:
        del path
        built.append(settings)
        return _parsed()

    with patch(_PARSE, new=record):
        await parsing.recognise(b"%PDF-1.4", "scan.pdf")

    assert built[0].pdf_parser.liteparse_max_pages == parsing.MAX_OCR_PAGES
    assert built[0].pdf_parser.liteparse_timeout_seconds == parsing.PARSE_TIMEOUT_SECONDS


async def test_analysis_bounds_pymupdf_semantic_work_and_both_local_parsers_time() -> None:
    """A byte-small PDF must not buy unbounded native work or retained output."""
    built: list[object] = []

    async def record(settings: object, path: Path) -> Document:
        del path
        built.append(settings)
        return _parsed()

    with patch(_PARSE, new=record):
        await parsing.analyze(b"%PDF-1.4", "notes.pdf", parser="pymupdf")

    pdf = built[0].pdf_parser
    assert pdf.pymupdf_max_pages == parsing.MAX_ANALYSIS_PAGES
    assert pdf.pymupdf_max_content_chars == parsing.PYMUPDF_MAX_CONTENT_CHARS
    assert pdf.pymupdf_max_tables == parsing.PYMUPDF_MAX_TABLES
    assert pdf.pymupdf_max_images == parsing.PYMUPDF_MAX_IMAGES
    assert pdf.pymupdf_max_image_bytes == parsing.PYMUPDF_MAX_IMAGE_BYTES
    assert pdf.pymupdf_timeout_seconds == parsing.PARSE_TIMEOUT_SECONDS
    assert pdf.liteparse_max_pages == parsing.MAX_ANALYSIS_PAGES
    assert pdf.liteparse_timeout_seconds == parsing.PARSE_TIMEOUT_SECONDS


@pytest.mark.security
async def test_a_document_over_a_semantic_budget_gets_a_controlled_refusal() -> None:
    with (
        patch(
            _PARSE,
            new=AsyncMock(side_effect=DocumentLimitExceeded("extracted characters", 100)),
        ),
        pytest.raises(BadRequestError) as caught,
    ):
        await parsing.analyze(b"%PDF-1.4", "dense.pdf", parser="pymupdf")

    assert caught.value.details["budget"] == "extracted characters"
    assert caught.value.details["limit"] == 100
    assert "Split it" in caught.value.message


@pytest.mark.security
async def test_a_wall_timeout_kills_and_reaps_the_parser_child() -> None:
    child = object()
    reaped = AsyncMock()
    with (
        patch(
            "app.services.ml.parsing._transfer_parse_child",
            new=AsyncMock(side_effect=TimeoutError),
        ),
        patch("app.services.ml.parsing._reap_parse_child", new=reaped),
        pytest.raises(RuntimeError, match="wall deadline"),
    ):
        await parsing._exchange_parse_child(
            child,
            b"{}",
            parsing.asyncio.get_running_loop().time() + 1,
        )

    reaped.assert_awaited_once_with(child)


async def test_cancellation_kills_and_reaps_the_parser_child() -> None:
    child = object()
    waiting = parsing.asyncio.Event()
    reaped = AsyncMock()

    async def transfer(_proc: object, _payload: bytes) -> tuple[bytes, bytes]:
        await waiting.wait()
        return b"", b""

    with (
        patch("app.services.ml.parsing._transfer_parse_child", new=transfer),
        patch("app.services.ml.parsing._reap_parse_child", new=reaped),
    ):
        task = parsing.asyncio.create_task(
            parsing._exchange_parse_child(
                child,
                b"{}",
                parsing.asyncio.get_running_loop().time() + 10,
            )
        )
        await parsing.asyncio.sleep(0)
        task.cancel()
        with pytest.raises(parsing.asyncio.CancelledError):
            await task

    reaped.assert_awaited_once_with(child)


async def test_broken_child_pipe_is_reaped_and_reported() -> None:
    child = object()
    reaped = AsyncMock()
    with (
        patch(
            "app.services.ml.parsing._transfer_parse_child",
            new=AsyncMock(side_effect=BrokenPipeError),
        ),
        patch("app.services.ml.parsing._reap_parse_child", new=reaped),
        pytest.raises(RuntimeError, match="before replying"),
    ):
        await parsing._exchange_parse_child(
            child,
            b"{}",
            parsing.asyncio.get_running_loop().time() + 1,
        )

    reaped.assert_awaited_once_with(child)


async def test_transfer_bounds_protocol_output_and_reports_child_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success = _FakeProcess(stdout=[b'{"ok":false,"kind":"value_error"}'])
    response, diagnostic = await parsing._transfer_parse_child(
        cast(asyncio.subprocess.Process, success), b"settings"
    )
    assert response == b'{"ok":false,"kind":"value_error"}'
    assert diagnostic == b""
    assert success.stdin.written == b"settings"
    assert success.stdin.closed is True

    monkeypatch.setattr(parsing, "PARSE_RESPONSE_MAX_BYTES", 4)
    oversized = _FakeProcess(stdout=[b"12345", b"discarded"])
    with pytest.raises(RuntimeError, match="too much output"):
        await parsing._transfer_parse_child(
            cast(asyncio.subprocess.Process, oversized), b"settings"
        )

    failed = _FakeProcess(stderr=[b"diagnostic"], returncode=9)
    with pytest.raises(RuntimeError, match="without a result"):
        await parsing._transfer_parse_child(cast(asyncio.subprocess.Process, failed), b"settings")


@pytest.mark.parametrize(
    ("response", "failure"),
    [
        (b'{"ok":false,"kind":"limit","budget":"pages","maximum":2}', DocumentLimitExceeded),
        (b'{"ok":false,"kind":"value_error"}', ValueError),
        (b'{"ok":false,"kind":"runtime_error"}', RuntimeError),
        (b'{"ok":false,"kind":"bad_document"}', parsing._InvalidDocumentError),
        (b'{"ok":false,"kind":"limit","budget":1,"maximum":2}', RuntimeError),
        (b'{"ok":false,"kind":"unknown"}', RuntimeError),
        (b'{"ok":"yes"}', RuntimeError),
        (b"not json", RuntimeError),
        (b"\xff", RuntimeError),
    ],
)
def test_child_failure_protocol_is_validated(
    response: bytes,
    failure: type[Exception],
) -> None:
    with pytest.raises(failure):
        parsing._parse_child_response(response)


def test_child_success_protocol_restores_a_document() -> None:
    response = json.dumps({"ok": True, "document": _parsed().model_dump(mode="json")}).encode()
    assert parsing._parse_child_response(response).pages[0].content == "recognised"

    malformed = json.dumps({"ok": True, "document": {"pages": []}}).encode()
    with pytest.raises(RuntimeError, match="malformed document"):
        parsing._parse_child_response(malformed)


async def test_spawn_failures_are_controlled_and_eventual_children_are_reaped() -> None:
    with (
        patch(
            "app.services.ml.parsing.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=OSError),
        ),
        pytest.raises(RuntimeError, match="could not be started"),
    ):
        await parsing._spawn_parse_child(
            Path("document.pdf"), parsing.asyncio.get_running_loop().time() + 1
        )

    child = object()
    release = parsing.asyncio.Event()
    reaped = AsyncMock()

    async def delayed_spawn(*_args: object, **_kwargs: object) -> object:
        await release.wait()
        return child

    async def release_after_timeout() -> None:
        await parsing.asyncio.sleep(0.01)
        release.set()

    releaser = parsing.asyncio.create_task(release_after_timeout())
    with (
        patch(
            "app.services.ml.parsing.asyncio.create_subprocess_exec",
            new=delayed_spawn,
        ),
        patch("app.services.ml.parsing._reap_parse_child", new=reaped),
        pytest.raises(RuntimeError, match="wall deadline"),
    ):
        await parsing._spawn_parse_child(
            Path("document.pdf"), parsing.asyncio.get_running_loop().time()
        )
    await releaser
    reaped.assert_awaited_once_with(child)


async def test_cancellation_racing_spawn_reaps_the_eventual_child() -> None:
    child = object()
    started = parsing.asyncio.Event()
    release = parsing.asyncio.Event()
    reaped = AsyncMock()

    async def delayed_spawn(*_args: object, **_kwargs: object) -> object:
        started.set()
        await release.wait()
        return child

    with (
        patch(
            "app.services.ml.parsing.asyncio.create_subprocess_exec",
            new=delayed_spawn,
        ),
        patch("app.services.ml.parsing._reap_parse_child", new=reaped),
    ):
        task = parsing.asyncio.create_task(
            parsing._spawn_parse_child(
                Path("document.pdf"),
                parsing.asyncio.get_running_loop().time() + 10,
            )
        )
        await started.wait()
        task.cancel()
        await parsing.asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(parsing.asyncio.CancelledError):
            await task

    reaped.assert_awaited_once_with(child)


async def test_settling_a_spawn_returns_a_child_or_none() -> None:
    child = object()

    async def succeed() -> object:
        return child

    successful = parsing.asyncio.ensure_future(succeed())
    assert await parsing._settle_parse_spawn(successful) is child

    async def fail() -> object:
        raise OSError

    failed = parsing.asyncio.ensure_future(fail())
    assert await parsing._settle_parse_spawn(failed) is None


@pytest.mark.security
@pytest.mark.parametrize("cancel", [False, True])
async def test_a_spawn_failure_after_the_caller_stops_preserves_its_refusal(cancel: bool) -> None:
    started = asyncio.Event()
    settling = asyncio.Event()
    release = asyncio.Event()
    reaped = AsyncMock()
    real_settle = parsing._settle_parse_spawn

    async def failed_spawn(*_args: object, **_kwargs: object) -> asyncio.subprocess.Process:
        started.set()
        await release.wait()
        raise OSError("process creation refused")

    async def settle(
        spawn: asyncio.Task[asyncio.subprocess.Process],
    ) -> asyncio.subprocess.Process | None:
        settling.set()
        return await real_settle(spawn)

    with (
        patch("app.services.ml.parsing.asyncio.create_subprocess_exec", new=failed_spawn),
        patch("app.services.ml.parsing._settle_parse_spawn", new=settle),
        patch("app.services.ml.parsing._reap_parse_child", new=reaped),
    ):
        task = asyncio.create_task(
            parsing._spawn_parse_child(
                Path("document.pdf"), asyncio.get_running_loop().time() + (10 if cancel else 0)
            )
        )
        await started.wait()
        if cancel:
            task.cancel()
        await settling.wait()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task

    reaped.assert_not_awaited()


@pytest.mark.security
async def test_a_broken_output_pipe_cancels_the_other_pending_reader() -> None:
    reading_diagnostic = asyncio.Event()
    diagnostic_cancelled = asyncio.Event()

    class BrokenReader(_FakeReader):
        async def read(self, _size: int) -> bytes:
            await reading_diagnostic.wait()
            raise OSError("output pipe failed")

    class WaitingReader(_FakeReader):
        async def read(self, _size: int) -> bytes:
            reading_diagnostic.set()
            try:
                await asyncio.Event().wait()
            finally:
                diagnostic_cancelled.set()
            return b""

    process = _FakeProcess()
    process.stdout = BrokenReader()
    process.stderr = WaitingReader()
    with pytest.raises(OSError, match="output pipe failed"):
        await parsing._transfer_parse_child(cast(asyncio.subprocess.Process, process), b"settings")

    assert diagnostic_cancelled.is_set()
    assert process.stdin.closed


async def test_reaping_absorbs_cancellation_and_kills_the_process_group() -> None:
    process = _FakeProcess(stdout=[b"out"], stderr=[b"err"])
    signals: list[tuple[int, object]] = []
    started = parsing.asyncio.Event()
    release = parsing.asyncio.Event()
    real_cleanup = parsing._kill_and_reap_parse_child

    async def delayed_cleanup(proc: object) -> None:
        started.set()
        await release.wait()
        await real_cleanup(proc)

    with (
        patch("app.services.ml.parsing._kill_and_reap_parse_child", new=delayed_cleanup),
        patch(
            "app.services.ml.parsing.os.killpg",
            side_effect=lambda pid, sig: signals.append((pid, sig)),
        ),
    ):
        task = parsing.asyncio.create_task(
            parsing._reap_parse_child(cast(asyncio.subprocess.Process, process))
        )
        await started.wait()
        task.cancel()
        await parsing.asyncio.sleep(0)
        assert not task.done()
        release.set()
        await task

    assert signals == [(process.pid, parsing.signal.SIGKILL)]
    assert process.stdin.closed is True


async def test_transfer_cancellation_stops_its_pipe_readers() -> None:
    release = parsing.asyncio.Event()

    class WaitingReader(_FakeReader):
        async def read(self, _size: int) -> bytes:
            await release.wait()
            return b""

    process = _FakeProcess()
    process.stdout = WaitingReader()
    process.stderr = WaitingReader()
    task = parsing.asyncio.create_task(
        parsing._transfer_parse_child(cast(asyncio.subprocess.Process, process), b"settings")
    )
    await parsing.asyncio.sleep(0)
    task.cancel()
    with pytest.raises(parsing.asyncio.CancelledError):
        await task


async def test_parse_child_logs_bounded_diagnostics_and_restores_the_document() -> None:
    response = json.dumps({"ok": True, "document": _parsed().model_dump(mode="json")}).encode()
    child = object()
    with (
        patch("app.services.ml.parsing._spawn_parse_child", new=AsyncMock(return_value=child)),
        patch("app.services.ml.parsing._reap_parse_child", new=AsyncMock()),
        patch(
            "app.services.ml.parsing._exchange_parse_child",
            new=AsyncMock(return_value=(response, b"diagnostic")),
        ),
    ):
        document = await parsing._parse_in_child(parsing.RAGSettings(), Path("document.pdf"))

    assert document.pages[0].content == "recognised"


async def test_cancellation_after_spawn_cannot_orphan_the_parser_child() -> None:
    child = _FakeProcess()
    child.returncode = None
    reaped = AsyncMock()
    with (
        patch("app.services.ml.parsing._spawn_parse_child", new=AsyncMock(return_value=child)),
        patch(
            "app.services.ml.parsing._exchange_parse_child",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        patch("app.services.ml.parsing._reap_parse_child", new=reaped),
        pytest.raises(asyncio.CancelledError),
    ):
        await parsing._parse_in_child(parsing.RAGSettings(), Path("document.pdf"))

    reaped.assert_awaited_once_with(child)


async def test_a_parse_is_refused_outright_when_every_slot_is_busy() -> None:
    """Refused rather than queued: a caller parked behind four scans has timed out.

    The rate limit counts starts and cannot see what is still running, so this is
    the only thing bounding concurrent OCR.
    """
    with patch("app.services.ml.parsing.app_settings.ML_MAX_CONCURRENT_PARSES", 1):
        async with parsing.admitted("held.pdf"):
            with pytest.raises(RateLimitError) as caught:
                async with parsing.admitted("refused.pdf"):
                    pass

    assert caught.value.details["retry_after_seconds"] > 0


async def test_a_slot_is_given_back_when_a_parse_fails() -> None:
    with patch("app.services.ml.parsing.app_settings.ML_MAX_CONCURRENT_PARSES", 1):
        with contextlib.suppress(RuntimeError):
            async with parsing.admitted("first.pdf"):
                raise RuntimeError("boom")
        async with parsing.admitted("second.pdf"):
            pass


async def test_the_parser_child_starts_with_hard_limits_and_its_own_session() -> None:
    """The native parser must be killable and isolated from the API process."""
    child = object()
    spawned = AsyncMock(return_value=child)
    loop = parsing.asyncio.get_running_loop()

    with (
        patch("app.services.ml.parsing.asyncio.create_subprocess_exec", spawned),
        patch.dict("os.environ", {"TOKIO_WORKER_THREADS": "64"}),
    ):
        result = await parsing._spawn_parse_child(Path("document.pdf"), loop.time() + 1)

    assert result is child
    args = spawned.await_args.args
    assert args[:3] == (parsing.sys.executable, "-I", str(parsing._PARSE_WORKER_PATH))
    assert int(args[3]) > parsing.PARSE_TIMEOUT_SECONDS
    assert int(args[4]) == parsing.PARSE_MEMORY_LIMIT_BYTES
    assert spawned.await_args.kwargs["start_new_session"] is True
    environment = spawned.await_args.kwargs["env"]
    assert environment["TOKIO_WORKER_THREADS"] == "1"
    assert environment["TMPDIR"] == str(Path("document.pdf").parent)
