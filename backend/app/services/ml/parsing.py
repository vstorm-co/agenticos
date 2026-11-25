"""Reading a document that belongs to no collection.

The parsers in `app/services/rag` were written for ingestion: a file arrives,
is read into pages and chunks, and the chunks are embedded into a collection.
FA-070 and FA-071 ask for the first half of that on its own - a caller hands
over a file and gets its structure back, with nothing stored and no collection
involved. So this module is the ingestion pipeline's parsing stage, driven by
a request's settings instead of a collection's.

**The file exists for the length of the call.** Every parser here takes a path
because the engines underneath them do - PDFium and PyMuPDF both read files -
so the bytes are written to a private temporary directory and the directory is
removed on the way out, on the failure path as well as the success one. Nothing
reaches the deployment's document storage: this service does not become a
second place a tenant's documents live.

**OCR is not a flag on analysis, it is the other service.** `analyze` reads
what the document already carries, which for a born-digital PDF is everything
and costs milliseconds. `recognise` turns recognition on for every page whether
the text layer looks thin or not, because a caller who asked for OCR asked for
the pages to be read as images - the auto-detection that makes ingestion cheap
would quietly answer a different question here.
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import tempfile
import weakref
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from typing import cast

from app.core.blocking import run_blocking, write_bytes_cancel_safe
from app.core.config import settings as app_settings
from app.core.exceptions import BadRequestError, ExternalServiceError, RateLimitError
from app.core.field_errors import refused_field
from app.services.rag.config import (
    LITEPARSE_PDF_FORMATS,
    NATIVE_FORMATS,
    PARSER_FORMATS,
    PYMUPDF_MAX_CONTENT_CHARS,
    PYMUPDF_MAX_IMAGE_BYTES,
    PYMUPDF_MAX_IMAGES,
    PYMUPDF_MAX_TABLES,
    DocumentParser,
    PdfParser,
    RAGSettings,
)
from app.services.rag.documents import DocumentLimitExceeded
from app.services.rag.models import Document

logger = logging.getLogger(__name__)

ANALYSIS_PARSERS: tuple[str, ...] = ("liteparse", "pymupdf")
"""The parsers this service offers, and why the third one is not here.

LlamaParse is a vendor that bills against a key sealed for a *collection*; a
call that names no collection has no key to reach, and inventing a
deployment-wide one is the thing `app/core/vault.py` exists to prevent. So the
two local engines are the offering, which is also what makes this service one
that runs entirely on the operator's own machines.
"""

DEFAULT_PARSER = "liteparse"
"""What a caller gets when they name no parser: the layout-aware one."""

OCR_PARSER = "liteparse"
"""The one parser that recognises text on a page rather than reading a text layer."""

RECOGNISABLE_FORMATS: frozenset[str] = frozenset(LITEPARSE_PDF_FORMATS - NATIVE_FORMATS)
"""What the OCR service accepts: pages that can be rendered as images.

Narrower than what the parser reads, and the subtraction is the load-bearing
part. `DocumentProcessor.process_file` routes `.txt`, `.md` and `.docx` to the
native parsers *before* it consults the configured LiteParse one, so a `.docx`
accepted here would have its existing paragraphs extracted and its scanned pages
silently dropped - an answer that looks like recognition, is not one, and says
nothing about what it left out. A caller with a scanned `.docx` converts it to
PDF, which the refusal says.
"""

MAX_OCR_PAGES = 200
"""How many pages one OCR call may recognise.

The ingestion default is 1000, which is right for a document somebody chose to
index and wrong for a synchronous endpoint: recognition is seconds a page, so a
thousand-page scan is an hour of one worker's parsing pool held by one request.
A caller with more pages than this splits the document, which the refusal in
`DocumentProcessor` does not say - so the ceiling is applied here, where it can be
explained.
"""

PARSE_TIMEOUT_SECONDS = 120.0
"""How long one parse may take before the caller is told it did not finish.

Also narrower than ingestion's 600: nothing is waiting on an ingestion, and a
caller is waiting on this. The ML parent enforces it as a hard wall deadline on
a child process, so native parsing cannot keep consuming capacity after the
request has ended."""

MAX_ANALYSIS_PAGES = 1000
"""The largest document the synchronous analysis service reads in one call."""

PARSE_MEMORY_LIMIT_BYTES = 768 * 1024 * 1024
"""Address-space ceiling applied inside each parser child before app imports.

This is a per-child ceiling. Deployment sizing must account for the API
processes, per-process admissions, and bounded parent protocol buffers.
"""

PARSE_RESPONSE_MAX_BYTES = 64 * 1024 * 1024
"""Largest parser-child protocol response retained by the API process."""

PARSE_STDERR_MAX_BYTES = 64 * 1024
"""Largest diagnostic prefix retained from a failed parser child."""

_PARSE_CPU_GRACE_SECONDS = 5
_PARSE_WORKER_PATH = Path(__file__).with_name("_parse_worker.py")

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50


@dataclass(frozen=True)
class ParsedPage:
    """One page, as the parser rendered it."""

    page_num: int
    content: str


@dataclass(frozen=True)
class ParsedDocument:
    """A document read into pages and prepared chunks."""

    filename: str
    filetype: str
    byte_size: int
    content_hash: str
    pages: tuple[ParsedPage, ...]
    chunks: tuple[str, ...]


async def analyze(
    content: bytes,
    filename: str,
    *,
    parser: str = DEFAULT_PARSER,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    chunking_strategy: str = "recursive",
) -> ParsedDocument:
    """Read a document's structure and prepare its content.

    Raises:
        BadRequestError: If the parser is not one this service offers, if the
            chunking asks for more overlap than chunk, if it cannot read this
            file type, or if the document yields no text - which for a scan means
            OCR is the service to call instead.
    """
    if parser not in ANALYSIS_PARSERS:
        raise refused_field("parser", f"Choose one of: {', '.join(ANALYSIS_PARSERS)}.")
    if chunk_overlap >= chunk_size:
        # Not merely nonsense: the splitter accepts it, and an overlap equal to
        # the chunk advances by about one separator per chunk while keeping an
        # almost complete copy of the last one. A document then comes back
        # multiplied - in this process's memory and in the response - which turns
        # a legal 25 MB upload into hundreds of megabytes. `IngestionConfig`
        # refuses the same shape for the same reason.
        raise refused_field(
            "chunk_overlap",
            f"The overlap has to be smaller than the chunk; {chunk_overlap} is not "
            f"smaller than {chunk_size}.",
        )
    settings = RAGSettings(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunking_strategy=chunking_strategy,
        document_parser=DocumentParser(),
        pdf_parser=PdfParser(
            method=parser,
            pymupdf_max_pages=MAX_ANALYSIS_PAGES,
            pymupdf_max_content_chars=PYMUPDF_MAX_CONTENT_CHARS,
            pymupdf_max_tables=PYMUPDF_MAX_TABLES,
            pymupdf_max_images=PYMUPDF_MAX_IMAGES,
            pymupdf_max_image_bytes=PYMUPDF_MAX_IMAGE_BYTES,
            pymupdf_timeout_seconds=PARSE_TIMEOUT_SECONDS,
            liteparse_max_pages=MAX_ANALYSIS_PAGES,
            liteparse_timeout_seconds=PARSE_TIMEOUT_SECONDS,
        ),
    )
    return await _run(
        content, filename, settings=settings, parser=parser, readable=PARSER_FORMATS[parser]
    )


async def recognise(
    content: bytes,
    filename: str,
    *,
    language: str = "eng",
    ocr_server_url: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> ParsedDocument:
    """Recognise the text on every page of a document.

    Args:
        content: The file's bytes.
        filename: What it is called, which is what decides the parser route.
        language: A Tesseract language code, which is three letters (`deu`, not `de`).
        ocr_server_url: An OCR server on the deployment's own network to send
            pages to. `None` uses the recognition engine bundled with the parser.

    Raises:
        BadRequestError: If the file type cannot be recognised, or if nothing
            was read off the pages.
    """
    settings = RAGSettings(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        enable_ocr=True,
        document_parser=DocumentParser(),
        pdf_parser=PdfParser(
            method=OCR_PARSER,
            liteparse_auto_ocr=False,
            liteparse_ocr_language=language,
            liteparse_ocr_server_url=ocr_server_url,
            liteparse_max_pages=MAX_OCR_PAGES,
            liteparse_timeout_seconds=PARSE_TIMEOUT_SECONDS,
        ),
    )
    return await _run(
        content, filename, settings=settings, parser=OCR_PARSER, readable=RECOGNISABLE_FORMATS
    )


_admissions: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)
"""How many parses this worker will have in flight at once, per event loop.

Keyed by loop for the reason `app/core/blocking.py` keys its own limiter that
way: an `asyncio.Semaphore` binds to the loop that made it.
"""


def _admission() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _admissions.get(loop)
    if gate is None:
        gate = asyncio.Semaphore(app_settings.ML_MAX_CONCURRENT_PARSES)
        _admissions[loop] = gate
    return gate


@contextlib.asynccontextmanager
async def admitted(filename: str) -> AsyncGenerator[None]:
    """Hold one of this worker's parsing slots, or refuse straight away.

    The rate limit counts *starts* per minute and cannot see what is still
    running, so thirty admitted OCR calls are thirty recognitions in flight -
    each of them minutes of CPU - and the thirty-first waits behind them holding
    a database connection and a socket. This bounds the work rather than the
    arrivals, and refuses rather than queues: a caller told to come back in a
    moment can, and a caller parked for four minutes has already timed out
    somewhere the platform cannot see.
    """
    gate = _admission()
    if gate.locked():
        logger.info("Refusing an ML parse of %s: every parsing slot is busy", filename)
        raise RateLimitError(
            message=(
                "Every document-parsing slot on this worker is busy. Retry in a "
                "moment, or scale the ML replica."
            ),
            details={"retry_after_seconds": 5, "stage": "admission"},
        )
    async with gate:
        yield


class _InvalidDocumentError(Exception):
    """The isolated parser classified the submitted bytes as malformed."""


async def _parse_in_child(settings: RAGSettings, path: Path) -> Document:
    """Run parsing in a resource-limited child that cannot outlive this call.

    Native parsers cannot be interrupted in a thread. The child owns all parser
    CPU and allocations, applies CPU/address-space limits before importing the
    pipeline, and is killed as a process group on wall timeout or cancellation.
    The API's shared file-I/O pool is used only for the bounded input write and
    cleanup, never for the attacker-controlled parse itself.
    """
    payload = settings.model_dump_json().encode("utf-8")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + PARSE_TIMEOUT_SECONDS
    proc = await _spawn_parse_child(path, deadline)
    try:
        response, stderr = await _exchange_parse_child(proc, payload, deadline)
    finally:
        # A converter can leave descendants after its launcher exits. Clear the
        # owned group on success and failure, including cancellation at spawn.
        await _reap_parse_child(proc)
    if stderr:
        logger.warning(
            "ml_parse_child_stderr",
            extra={"stderr": stderr.decode("utf-8", "replace")},
        )
    return _parse_child_response(response)


async def _spawn_parse_child(path: Path, deadline: float) -> asyncio.subprocess.Process:
    """Start the isolated parser within its wall budget, reaping spawn races."""
    remaining = max(deadline - asyncio.get_running_loop().time(), 0.0)
    spawn = asyncio.ensure_future(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(_PARSE_WORKER_PATH),
            str(int(PARSE_TIMEOUT_SECONDS) + _PARSE_CPU_GRACE_SECONDS),
            str(PARSE_MEMORY_LIMIT_BYTES),
            str(path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env={
                **os.environ,
                "TMPDIR": str(path.parent),
                "TMP": str(path.parent),
                "TEMP": str(path.parent),
                # LiteParse's default Tokio pool scales with host CPUs and can
                # exhaust this process's address-space budget before parsing.
                "TOKIO_WORKER_THREADS": "1",
            },
        )
    )
    try:
        async with asyncio.timeout(remaining):
            await asyncio.wait({spawn})
        return spawn.result()
    except TimeoutError:
        proc = await _settle_parse_spawn(spawn)
        if proc is not None:
            await _reap_parse_child(proc)
        raise RuntimeError("The isolated document parser exceeded its wall deadline") from None
    except asyncio.CancelledError:
        proc = await _settle_parse_spawn(spawn)
        if proc is not None:
            await _reap_parse_child(proc)
        raise
    except OSError:
        raise RuntimeError("The isolated document parser could not be started") from None


async def _settle_parse_spawn(
    spawn: asyncio.Task[asyncio.subprocess.Process],
) -> asyncio.subprocess.Process | None:
    """Wait out a shielded spawn while absorbing repeated cancellation."""
    while not spawn.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait({spawn})
    try:
        return spawn.result()
    except Exception, asyncio.CancelledError:
        return None


async def _exchange_parse_child(
    proc: asyncio.subprocess.Process, payload: bytes, deadline: float
) -> tuple[bytes, bytes]:
    """Exchange one bounded request and kill the child on timeout/cancellation."""
    remaining = max(deadline - asyncio.get_running_loop().time(), 0.0)
    try:
        return await asyncio.wait_for(_transfer_parse_child(proc, payload), timeout=remaining)
    except TimeoutError:
        await _reap_parse_child(proc)
        raise RuntimeError("The isolated document parser exceeded its wall deadline") from None
    except asyncio.CancelledError:
        await _reap_parse_child(proc)
        raise
    except OSError:
        await _reap_parse_child(proc)
        raise RuntimeError("The isolated document parser exited before replying") from None


async def _transfer_parse_child(
    proc: asyncio.subprocess.Process, payload: bytes
) -> tuple[bytes, bytes]:
    """Write settings, drain bounded output streams, and reap a normal exit."""
    writer = cast(asyncio.StreamWriter, proc.stdin)
    writer.write(payload)
    await writer.drain()
    writer.close()
    await writer.wait_closed()

    stdout = cast(asyncio.StreamReader, proc.stdout)
    stderr = cast(asyncio.StreamReader, proc.stderr)
    stdout_task = asyncio.create_task(_read_bounded(stdout, PARSE_RESPONSE_MAX_BYTES))
    stderr_task = asyncio.create_task(_read_bounded(stderr, PARSE_STDERR_MAX_BYTES))
    try:
        (
            (response, response_exceeded),
            (diagnostic, _diagnostic_exceeded),
            returncode,
        ) = await asyncio.gather(stdout_task, stderr_task, proc.wait())
    finally:
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    if response_exceeded:
        raise RuntimeError("The isolated document parser produced too much output")
    if returncode != 0:
        if diagnostic:
            logger.warning(
                "ml_parse_child_failed",
                extra={
                    "returncode": returncode,
                    "stderr": diagnostic.decode("utf-8", "replace"),
                },
            )
        raise RuntimeError("The isolated document parser exited without a result")
    return response, diagnostic


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    """Drain a stream to EOF while retaining at most a bounded prefix."""
    captured = bytearray()
    exceeded = False
    while chunk := await stream.read(65536):
        if exceeded:
            continue
        captured.extend(chunk)
        if len(captured) > limit:
            exceeded = True
            del captured[limit:]
    return bytes(captured), exceeded


def _parse_child_response(response: bytes) -> Document:
    """Validate the child protocol and restore its controlled failure class."""
    try:
        decoded = json.loads(response.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        raise RuntimeError("The isolated document parser returned a malformed result") from None
    valid_envelope = isinstance(decoded, dict) and isinstance(decoded.get("ok"), bool)
    if not valid_envelope:
        raise RuntimeError("The isolated document parser returned a malformed result")
    if decoded["ok"]:
        try:
            return Document.model_validate(decoded.get("document"))
        except ValueError:
            raise RuntimeError(
                "The isolated document parser returned a malformed document"
            ) from None

    kind = decoded.get("kind")
    if kind == "limit":
        budget = decoded.get("budget")
        maximum = decoded.get("maximum")
        if (
            isinstance(budget, str)
            and isinstance(maximum, int | float)
            and not isinstance(maximum, bool)
        ):
            raise DocumentLimitExceeded(budget, maximum)
    if kind == "value_error":
        raise ValueError("The document produced no indexable content")
    if kind == "runtime_error":
        raise RuntimeError("The document parser engine failed")
    if kind == "bad_document":
        raise _InvalidDocumentError
    raise RuntimeError("The isolated document parser returned a malformed result")


async def _reap_parse_child(proc: asyncio.subprocess.Process) -> None:
    """Kill and reap a parser child despite repeated caller cancellation."""
    cleanup = asyncio.ensure_future(_kill_and_reap_parse_child(proc))
    while not cleanup.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait({cleanup})
    cleanup.result()


async def _kill_and_reap_parse_child(proc: asyncio.subprocess.Process) -> None:
    """Kill the parser's process group, drain its pipes, and reap its leader."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    cast(asyncio.StreamWriter, proc.stdin).close()
    await asyncio.gather(
        _drain_parse_stream(cast(asyncio.StreamReader, proc.stdout)),
        _drain_parse_stream(cast(asyncio.StreamReader, proc.stderr)),
        proc.wait(),
    )


async def _drain_parse_stream(stream: asyncio.StreamReader) -> None:
    """Discard a killed child's pipe so the transport can finish reaping it."""
    while await stream.read(65536):
        pass


async def _run(
    content: bytes,
    filename: str,
    *,
    settings: RAGSettings,
    parser: str,
    readable: frozenset[str] | set[str],
) -> ParsedDocument:
    """Write the bytes down, parse them, and take the directory away again."""
    suffix = Path(filename).suffix.lower()
    if suffix not in readable:
        raise refused_field(
            "file",
            f"{parser} reads {', '.join(sorted(readable))}; it cannot read {suffix or 'a file with no extension'}.",
        )

    async with admitted(filename):
        workspace = Path(tempfile.mkdtemp(prefix="ml-parse-"))
        try:
            path = workspace / f"document{suffix}"
            await write_bytes_cancel_safe(path, content)
            try:
                document = await _parse_in_child(settings, path)
            except DocumentLimitExceeded as exc:
                logger.info(
                    "An ML parse exceeded its %s budget for %s",
                    exc.budget,
                    filename,
                )
                raise BadRequestError(
                    message=(
                        "This document exceeds the synchronous parsing limits. "
                        "Split it into smaller documents and try again."
                    ),
                    details={
                        "filename": filename,
                        "parser": parser,
                        "stage": "parse",
                        "budget": exc.budget,
                        "limit": exc.maximum,
                    },
                ) from exc
            except ValueError as exc:
                logger.info("An ML parse produced nothing for %s", filename, exc_info=True)
                raise BadRequestError(
                    message=(
                        "Nothing could be read from this document. If it is a scan or a "
                        "photograph, call the OCR service rather than document analysis."
                    ),
                    details={"filename": filename, "parser": parser},
                ) from exc
            except RuntimeError as exc:
                # Runtime failures are the deployment's rather than the caller's:
                # the isolated child could not start, crossed a hard resource
                # ceiling, or its parser engine failed.
                logger.warning("The %s engine failed on %s", parser, filename, exc_info=True)
                raise ExternalServiceError(
                    message="The document could not be parsed by this deployment's engine.",
                    details={"filename": filename, "parser": parser, "stage": "parse"},
                ) from exc
            except Exception as exc:
                # Anything else is the bytes. `python-docx` raises
                # `PackageNotFoundError` on a file that is not a zip, PyMuPDF its
                # own on a truncated PDF, and neither is a `ValueError` or a
                # `RuntimeError` - so without this a malformed upload answered 500
                # and the usage log skipped it, because the facade records an
                # `AppException` and nothing else. A parser handed arbitrary bytes
                # failing in an unexpected way is overwhelmingly a bad file.
                logger.info("A malformed upload failed to parse: %s", filename, exc_info=True)
                raise BadRequestError(
                    message=f"This file could not be read as {suffix.lstrip('.') or 'a document'}.",
                    details={"filename": filename, "parser": parser, "stage": "parse"},
                ) from exc
        finally:
            await run_blocking(rmtree, workspace, True)

    return ParsedDocument(
        filename=filename,
        filetype=document.metadata.filetype,
        byte_size=len(content),
        content_hash=document.metadata.content_hash,
        pages=tuple(
            ParsedPage(page_num=page.page_num, content=page.content) for page in document.pages
        ),
        chunks=tuple(chunk.chunk_content or "" for chunk in document.chunked_pages or []),
    )
