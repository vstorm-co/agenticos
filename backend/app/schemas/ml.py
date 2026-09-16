"""The ML services' REST contracts.

Written to be read by somebody integrating from outside this repository, which
is why every field carries a description: the generated reference at `/docs` is
the contract FA-069 asks for, and a field described nowhere is a field an
integrator has to guess.

Nothing here has a `*Create` or `*Update` shape, because nothing is stored. A
request is an instruction and a response is a result; the only persistent object
on this surface is the record of the call, which is read and never written by a
client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema

if TYPE_CHECKING:
    from app.services.ml import parsing, pii

ParserLiteral = Literal["liteparse", "pymupdf"]


class MLServiceEntryRead(BaseSchema):
    """One row of the coverage matrix."""

    id: str = Field(description="The service id, which is also what a call record names")
    family: str = Field(description="The B01 service family this belongs to")
    requirements: list[str] = Field(description="The requirement ids this row answers")
    endpoint: str | None = Field(
        description="The REST path that serves it, or null where nothing does yet"
    )
    engine: str = Field(description="What performs the work on this deployment")
    state: str = Field(
        description=(
            "`served` - an endpoint here answers it; `dependency` - required and "
            "something is missing, named in the note; `prepared` - architecture "
            "preparation in B01, with no engine shipped."
        )
    )
    note: str = Field(description="What a caller gets, or what is still missing")


class MLServiceCatalogRead(BaseSchema):
    """Every service family, and how far each is delivered here."""

    items: list[MLServiceEntryRead]
    total: int


class ParsedPageRead(BaseSchema):
    """One page as the parser rendered it."""

    page_num: int
    content: str


class ParsedDocumentRead(BaseSchema):
    """A document read into pages and prepared chunks."""

    filename: str
    filetype: str = Field(description="The extension the file was read as, without the dot")
    byte_size: int = Field(description="How many bytes were submitted")
    content_hash: str = Field(description="SHA-256 of the submitted bytes")
    pages: list[ParsedPageRead] = Field(
        description="The pages, in order. A page with nothing readable on it is omitted."
    )
    chunks: list[str] = Field(
        description="The pages split for downstream use, using the requested chunking"
    )

    @classmethod
    def of(cls, document: parsing.ParsedDocument) -> ParsedDocumentRead:
        """Serialize what the parsing stage produced."""
        return cls(
            filename=document.filename,
            filetype=document.filetype,
            byte_size=document.byte_size,
            content_hash=document.content_hash,
            pages=[
                ParsedPageRead(page_num=page.page_num, content=page.content)
                for page in document.pages
            ],
            chunks=list(document.chunks),
        )


class TranscriptionRead(BaseSchema):
    """What was said in a recording."""

    text: str
    provider: str = Field(description="The provider the organization transcribed on")
    model: str


class PiiCategoryCountRead(BaseSchema):
    """How many matches one category accounted for."""

    category: str
    count: int


class PiiScanRequest(BaseSchema):
    """Text to scan for personal data."""

    text: str = Field(
        min_length=1,
        description="The text to scan. At most 200000 characters in one call.",
    )
    categories: list[str] | None = Field(
        default=None,
        description=(
            "Restrict the scan to these categories. Omit to scan every category this "
            "deployment detects, which `GET /ml/services` names."
        ),
    )


class PiiScanRead(BaseSchema):
    """What a scan found, and the text with it taken out."""

    counts: list[PiiCategoryCountRead] = Field(
        description="Every category scanned, including the ones that matched nothing"
    )
    total: int = Field(description="How many matches were found across all categories")
    redacted_text: str = Field(
        description="The submitted text with each match replaced by `[redacted:<category>]`"
    )

    @classmethod
    def of(cls, report: pii.PiiReport) -> PiiScanRead:
        """Serialize a scan's report."""
        return cls(
            counts=[
                PiiCategoryCountRead(category=entry.category, count=entry.count)
                for entry in report.counts
            ],
            total=report.total,
            redacted_text=report.redacted_text,
        )


class MLServiceCallRead(BaseSchema, TimestampSchema):
    """The record of one call, which holds no part of what was submitted."""

    id: UUID
    service: str
    status: str = Field(description="`succeeded` or `failed`")
    failure_stage: str | None = Field(default=None, description="Which part gave way, on a failure")
    failure_reason: str | None = Field(
        default=None, description="A sentence about the refusal, on a failure"
    )
    input_bytes: int
    units: int = Field(description="How much was produced, in `unit`")
    unit: str = Field(description="`pages`, `characters`, or empty on a failure")
    duration_ms: int


class MLServiceCallList(BaseSchema):
    items: list[MLServiceCallRead]
    total: int
