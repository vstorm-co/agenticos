"""`text.extract`: the text of a TXT, JSON, CSV, text PDF or DOCX file.

A PDF is read from its text layer, page by page. A page with no text and an
image on it is a scan, and a scan fails the step with
`TEXT_EXTRACTION_NEEDS_OCR`, naming the pages - general OCR is not what this
step does, and returning a scan as empty text would pass on a document that
says nothing. A corrupt document and an encrypted one each fail with their
own code, never the parser's message.

The format is the one the file's row recorded from its bytes, not its name.
The text travels inline to the next step, so it is bounded by `max_chars`;
write a long one to a file with `convert.text_to_file`.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes import _documents
from app.workflows.nodes._files import CSV, JSON, TEXT, ParseError, utf8

SourceFormat = Literal["txt", "json", "csv", "pdf", "docx"]

_FORMATS: dict[str, SourceFormat] = {
    TEXT: "txt",
    JSON: "json",
    CSV: "csv",
    "application/pdf": "pdf",
    files.DOCX: "docx",
}


class TextExtractConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_bytes: int = Field(default=25_000_000, ge=1, le=50_000_000)
    max_chars: int = Field(default=200_000, ge=1, le=2_000_000)


class TextExtractInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: FileRef


class TextExtractOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    source_format: SourceFormat
    page_count: int | None = Field(default=None, description="For a PDF, how many pages it has")


def _extract(data: bytes, source: SourceFormat) -> TextExtractOutput | Failed:
    if source == "pdf":
        extracted = _documents.pdf_text(data)
        if extracted.scanned_pages:
            return files.failed(
                "TEXT_EXTRACTION_NEEDS_OCR",
                "These pages are scans with no text layer, and reading them takes OCR",
                page_numbers=list(extracted.scanned_pages),
            )
        return TextExtractOutput(
            text="\n\n".join(page.strip() for page in extracted.pages).strip(),
            source_format="pdf",
            page_count=len(extracted.pages),
        )
    if source == "docx":
        return TextExtractOutput(text=_documents.docx_text(data), source_format="docx")
    return TextExtractOutput(text=utf8(data), source_format=source)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, TextExtractConfig) or not isinstance(node_input, TextExtractInput):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has no file to read")
    stored = await files.load(node_input.file, max_bytes=config.max_bytes)
    if isinstance(stored, Failed):
        return stored
    source = _FORMATS.get(stored.content_type)
    if source is None:
        return files.failed(
            "UNSUPPORTED_FORMAT",
            "Text can be read from TXT, JSON, CSV, a text PDF or DOCX - not from "
            f"{stored.content_type}. An encrypted or legacy Word file cannot be read either.",
            content_type=stored.content_type,
        )
    try:
        # The parsers are synchronous and can take seconds on a long document.
        result = await asyncio.to_thread(_extract, stored.data, source)
    except _documents.DocumentTooLarge:
        return files.failed(
            "DOCUMENT_TOO_LARGE", "This document unpacks to more than a document may"
        )
    except _documents.DocumentEncrypted:
        return files.failed("DOCUMENT_ENCRYPTED", "This document is protected by a password")
    except (_documents.DocumentCorrupt, ParseError):
        return files.failed("DOCUMENT_CORRUPT", "This document is damaged or not what it claims")
    if isinstance(result, Failed):
        return result
    if len(result.text) > config.max_chars:
        return files.failed(
            "TEXT_TOO_LONG",
            f"The text is {len(result.text)} characters, over this step's limit of "
            f"{config.max_chars}",
            char_count=len(result.text),
            max_chars=config.max_chars,
        )
    return Completed[TextExtractOutput](output=result)
