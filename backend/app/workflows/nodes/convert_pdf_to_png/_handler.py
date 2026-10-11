"""`convert.pdf_to_png`: chosen pages of a PDF as PNG images - to hand an agent a page to look at.

Each page's size is read before it is drawn, and a page whose picture would be
larger than `CHAT_IMAGE_MAX_PIXELS` at the chosen resolution fails the step
before anything is allocated - the same ceiling chat attachments are held to.
A page the document does not have fails with `PAGE_OUT_OF_RANGE`.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.workflows import files
from app.workflows.contracts.io import FileRef
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes import _documents
from app.workflows.nodes.convert_csv_to_json._handler import ConvertFileInput

MAX_PAGES = 20


class ConvertPdfToPngConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pages: tuple[int, ...] = Field(
        default=(1,),
        min_length=1,
        max_length=MAX_PAGES,
        json_schema_extra={"x-bindable": True},
        description="Which pages to render, counting from 1.",
    )
    dpi: int = Field(default=144, ge=36, le=300)
    max_bytes: int = Field(default=50_000_000, ge=1, le=100_000_000)


class RenderedPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int
    file: FileRef
    width: int
    height: int


class ConvertPdfToPngOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    images: tuple[RenderedPage, ...]


def _too_large(size: tuple[float, float], dpi: int) -> int | None:
    scale = dpi / 72
    pixels = int(size[0] * scale) * int(size[1] * scale)
    return pixels if pixels > settings.CHAT_IMAGE_MAX_PIXELS else None


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    if not isinstance(config, ConvertPdfToPngConfig) or not isinstance(
        node_input, ConvertFileInput
    ):
        return files.failed("FILE_STEP_NOT_CONFIGURED", "This step has no PDF to render")
    stored = await files.load(node_input.file, max_bytes=config.max_bytes)
    if isinstance(stored, Failed):
        return stored
    if stored.content_type != "application/pdf":
        return files.failed(
            "UNSUPPORTED_FORMAT",
            f"Only a PDF renders to images, not {stored.content_type}",
            content_type=stored.content_type,
        )
    try:
        sizes = await asyncio.to_thread(_documents.pdf_page_sizes, stored.data)
    except _documents.DocumentEncrypted:
        return files.failed("DOCUMENT_ENCRYPTED", "This document is protected by a password")
    except _documents.DocumentCorrupt:
        return files.failed("DOCUMENT_CORRUPT", "This document is damaged or not what it claims")
    for page in config.pages:
        if not 1 <= page <= len(sizes):
            return files.failed(
                "PAGE_OUT_OF_RANGE",
                f"Page {page} is not in this {len(sizes)}-page document",
                page=page,
                page_count=len(sizes),
            )
        pixels = _too_large(sizes[page - 1], config.dpi)
        if pixels is not None:
            return files.failed(
                "IMAGE_TOO_LARGE",
                f"Page {page} would be {pixels} pixels at {config.dpi} dpi, over the limit "
                f"of {settings.CHAT_IMAGE_MAX_PIXELS}",
                page=page,
                decoded_pixels=pixels,
                limit=settings.CHAT_IMAGE_MAX_PIXELS,
            )
    stem = (stored.filename or "document").rsplit(".", 1)[0]
    images: list[RenderedPage] = []
    for page in config.pages:
        png, width, height = await asyncio.to_thread(
            _documents.pdf_page_png, stored.data, page_number=page, dpi=config.dpi
        )
        image = await files.save(png, content_type="image/png", filename=f"{stem}-{page}.png")
        images.append(RenderedPage(page=page, file=image, width=width, height=height))
    return Completed[ConvertPdfToPngOutput](output=ConvertPdfToPngOutput(images=tuple(images)))
