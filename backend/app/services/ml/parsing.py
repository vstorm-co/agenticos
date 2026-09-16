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

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

from app.core.blocking import run_blocking, write_bytes_cancel_safe
from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.field_errors import refused_field
from app.services.rag.config import (
    LITEPARSE_PDF_FORMATS,
    PARSER_FORMATS,
    DocumentParser,
    PdfParser,
    RAGSettings,
)
from app.services.rag.documents import DocumentProcessor

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

RECOGNISABLE_FORMATS: frozenset[str] = frozenset(LITEPARSE_PDF_FORMATS)
"""What the OCR service accepts: pages that can be rendered as images.

Narrower than what the parser reads, deliberately. Handing a `.txt` file to a
recognition service and getting its own characters back is an answer that looks
like recognition and is not one, so the refusal comes first.
"""

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
        BadRequestError: If the parser is not one this service offers, if it
            cannot read this file type, or if the document yields no text -
            which for a scan means OCR is the service to call instead.
    """
    if parser not in ANALYSIS_PARSERS:
        raise refused_field("parser", f"Choose one of: {', '.join(ANALYSIS_PARSERS)}.")
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
        ),
    )
    return await _run(
        content, filename, settings=settings, parser=OCR_PARSER, readable=RECOGNISABLE_FORMATS
    )


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

    workspace = Path(tempfile.mkdtemp(prefix="ml-parse-"))
    try:
        path = workspace / f"document{suffix}"
        await write_bytes_cancel_safe(path, content)
        try:
            document = await DocumentProcessor(settings).process_file(path)
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
            # The parser's own message names a temporary path and carries the
            # engine's text, so it goes to the log and the caller is told which
            # stage failed on which file.
            logger.warning("The %s engine failed on %s", parser, filename, exc_info=True)
            raise ExternalServiceError(
                message="The document could not be parsed by this deployment's engine.",
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
