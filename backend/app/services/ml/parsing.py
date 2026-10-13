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

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import weakref
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

from app.core.blocking import run_blocking, write_bytes_cancel_safe
from app.core.config import settings as app_settings
from app.core.exceptions import BadRequestError, ExternalServiceError, RateLimitError
from app.core.field_errors import refused_field
from app.services.rag.config import (
    LITEPARSE_PDF_FORMATS,
    NATIVE_FORMATS,
    PARSER_FORMATS,
    DocumentParser,
    PdfParser,
    RAGSettings,
)
from app.services.rag.documents import DocumentProcessor
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
caller is waiting on this. It bounds the *request*, not the machine - a thread
already parsing runs to completion - which is why the page ceiling above is the
one that actually bounds cost."""

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
        pdf_parser=PdfParser(method=parser),
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
async def admitted(filename: str) -> AsyncIterator[None]:
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


def _parse(settings: RAGSettings, path: Path) -> Document:
    """Run the pipeline's parsing stage on a worker thread.

    `DocumentProcessor.process_file` is a coroutine that does synchronous work:
    PyMuPDF's parse, `python-docx`'s read, the file hash and the splitter all
    block, and only LiteParse moves its own parse off the loop. Awaiting it
    directly from a request handler therefore stops this worker answering
    anything - health, sign-in, every other tenant - for the length of a large
    PDF. So it runs on the dedicated file-io pool, in a loop of its own.

    `asyncio.run` in the pool thread is safe and is the point: the thread has no
    running loop, the coroutine awaits nothing that belongs to the request's, and
    no image describer is configured on this surface, so there is no outbound call
    inside it that would want the caller's loop back.
    """
    return asyncio.run(DocumentProcessor(settings).process_file(path))


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
                document = await run_blocking(_parse, settings, path)
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
                # The parser raises `RuntimeError` for the three things that are
                # the deployment's rather than the caller's: LibreOffice absent,
                # the parse timing out, and the engine refusing the file. Its own
                # message names a temporary path and carries the engine's text, so
                # it goes to the log and the caller is told which stage failed.
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
