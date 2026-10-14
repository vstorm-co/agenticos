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

from app.db.models.ml_service_call import MLServiceCall, TranscriptionSurface
from app.db.models.organization import DictationEngine
from app.schemas.base import BaseSchema, TimestampSchema
from app.services.speech_to_text import RecordingFormat

if TYPE_CHECKING:
    from app.repositories.ml_service_call import UsageSummary
    from app.services.ml import parsing, pii

ParserLiteral = Literal["liteparse", "pymupdf"]

ChunkingLiteral = Literal["recursive", "fixed", "markdown"]
"""The three strategies the splitter implements.

A closed set rather than a described string, because `_create_splitter` treats
anything it does not recognise as `recursive` - so `markdownn` would answer 200
with chunks split a different way and nothing would say so.
"""

OcrLanguageLiteral = Literal["eng", "pol"]
"""The Tesseract language packs the shipped image installs.

Not every code Tesseract knows: `backend/Dockerfile` installs `tesseract-ocr-eng`
and `tesseract-ocr-pol`, so any other code reaches an engine with no data for it
and fails inside the parse. A deployment that installs more packs widens this
list in the same change - which is the point of it being a list rather than a
free string that looked like it worked.
"""


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


class DictationRead(BaseSchema):
    """What was said, for the composer to insert.

    Nothing about the engine: the person did not choose it, and the
    organization's settings already say.
    """

    text: str


class DictationStatusRead(BaseSchema):
    """Whether the composer may offer server dictation for one agent, and how."""

    engine: DictationEngine = Field(description="The organization's dictation engine for `/chat`")
    ready: bool = Field(
        description=(
            "The engine is `server`, the agent is not archived, a provider and model "
            "resolve for it, the catalog offers them and the organization holds a "
            "credential for the provider. Configured, not proven: a revoked key fails "
            "on the first recording."
        )
    )
    server_available: bool = Field(
        description=(
            "`ready` without the engine or the archive check: a provider and model "
            "resolve for this agent, "
            "the catalog offers them and a credential exists. What a hosted page or a "
            "widget set to `server` needs, since the `/chat` engine does not gate them."
        )
    )
    max_seconds: int = Field(description="The organization's longest dictation, in seconds")
    provider: str | None = Field(
        description=(
            "The provider a recording would go to - the agent's override or the "
            "organization's. Null when none resolves."
        )
    )
    format: RecordingFormat = Field(
        description=(
            "What the browser records in for that provider: `webm` (what MediaRecorder "
            "makes) or `wav` (16 kHz mono 16-bit PCM, for a provider that takes neither "
            "WebM nor Opus). Decided by the speech-to-text catalog, so every client "
            "records the same way."
        )
    )


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
    units: int = Field(
        description=(
            "How much was produced, in `unit`. A transcription counts seconds of audio, "
            "rounded up, and 0 when no length was reported (`audio_ms` is null)"
        )
    )
    unit: str = Field(description="`pages`, `characters`, `seconds`, or empty on a failure")
    duration_ms: int = Field(description="How long the call took to answer, not the audio's length")
    provider: str | None = Field(
        default=None, description="The transcription provider, where one was chosen"
    )
    model: str | None = Field(default=None, description="The transcription model on `provider`")
    surface: TranscriptionSurface | None = Field(
        default=None,
        description=(
            "Where a transcription arrived: `chat` (dictation in the composer), `channel` "
            "(a bot's voice note), `api` (`POST /ml/audio/transcriptions`), `hosted` or "
            "`widget` (a visitor dictating on a hosted page or in a website widget). Null "
            "for other services and for older rows"
        ),
    )
    agent_id: UUID | None = Field(
        default=None,
        description="The agent a dictation was for, or the agent the channel bot serves",
    )
    channel_bot_id: UUID | None = Field(
        default=None, description="The channel bot a voice note arrived on"
    )
    audio_ms: int | None = Field(
        default=None,
        description=(
            "The recording's length in milliseconds. A dictation's is read from the "
            "recording itself where its container states one; otherwise the provider's "
            "figure, else the platform's metadata, else the browser's for a dictation. "
            "Null where nobody reported it"
        ),
    )

    @classmethod
    def of(cls, row: MLServiceCall, *, attributed: bool) -> MLServiceCallRead:
        """One record, with its agent, bot and surface only for a caller who may see them.

        `attributed` is `MLService.sees_attribution`; without it the three are
        null, as on a row written before they existed.
        """
        read = cls.model_validate(row)
        if attributed:
            return read
        return read.model_copy(update={"agent_id": None, "channel_bot_id": None, "surface": None})


class MLServiceCallList(BaseSchema):
    items: list[MLServiceCallRead]
    total: int


class TranscriptionUsageByAgent(BaseSchema):
    """One agent's share of the transcription summary."""

    agent_id: UUID
    name: str
    seconds: int = Field(
        description="Audio seconds, each recording rounded up as its call record's `units`"
    )
    count: int = Field(description="Successful transcriptions, with a length or without")


class TranscriptionUsageByChannel(BaseSchema):
    """One channel bot's share of the transcription summary."""

    channel_bot_id: UUID
    name: str
    seconds: int
    count: int


class TranscriptionUsageBySurface(BaseSchema):
    """One surface's share of the transcription summary."""

    surface: TranscriptionSurface | None = Field(
        description="Null for transcriptions recorded before surfaces were"
    )
    seconds: int
    count: int


class TranscriptionUsageSummary(BaseSchema):
    """An organization's successful transcriptions over a window, added up."""

    service: Literal["speech_to_text"]
    days: int
    seconds: int = Field(
        description=(
            "Audio seconds across the recordings whose length is known, each rounded up "
            "to the second as its call record's `units`, so this is the sum of what "
            "`GET /ml/calls` lists. An under-count whenever `count_unknown_length` is not 0"
        )
    )
    count: int = Field(description="Successful transcriptions in the window")
    count_unknown_length: int = Field(
        description=(
            "How many of them have no length: `gpt-4o(-mini)-transcribe` reports none, nor "
            "does a Mattermost voice note's metadata"
        )
    )
    by_agent: list[TranscriptionUsageByAgent] = Field(
        description="Longest first. Leaves out calls with no agent, or a deleted one"
    )
    by_channel: list[TranscriptionUsageByChannel] = Field(
        description="Longest first. Leaves out calls that did not arrive on a bot"
    )
    by_surface: list[TranscriptionUsageBySurface] = Field(
        description="Longest first; together these add up to `count`"
    )

    @classmethod
    def of(cls, summary: UsageSummary, *, days: int) -> TranscriptionUsageSummary:
        """Serialize a summary; its seconds are already whole, summed from `units`."""
        return cls(
            service="speech_to_text",
            days=days,
            seconds=summary.seconds,
            count=summary.count,
            count_unknown_length=summary.count_unknown_length,
            by_agent=[
                TranscriptionUsageByAgent(
                    agent_id=group.id,
                    name=group.name,
                    seconds=group.seconds,
                    count=group.count,
                )
                for group in summary.by_agent
            ],
            by_channel=[
                TranscriptionUsageByChannel(
                    channel_bot_id=group.id,
                    name=group.name,
                    seconds=group.seconds,
                    count=group.count,
                )
                for group in summary.by_channel
            ],
            by_surface=[
                TranscriptionUsageBySurface(
                    surface=group.surface,
                    seconds=group.seconds,
                    count=group.count,
                )
                for group in summary.by_surface
            ],
        )
