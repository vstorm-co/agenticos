"""The ML services, reached without an agent.

Everything the harness can do to a document, a recording or a piece of text, a
caller can ask for directly here: the same parsers ingestion uses, the same
detectors the guardrails enforce, the same transcription client a channel bot
reaches for a voice note. One implementation serves both, which is the point of
FA-069 - a second copy behind a standalone API would be a second set of answers.

**The tenant is the caller's, always.** Every method takes the `AuthContext` the
route resolved and never an organization id from a body, so a service cannot be
asked to work in a tenant the caller is not acting in. The one row this reaches
by id - a registered OCR server - is looked up through the service that scopes
it to the organization and the deployment's own rows, so naming another
tenant's server answers as if it did not exist.

**Nothing is stored but the fact of the call.** Results go back in the response
and are not retained; what is written is the usage record in `ml_service_calls`,
which holds no content. A failure writes its own record on a session of its own,
because the transaction that would have carried it is the one being rolled back
by the refusal it describes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, BadRequestError, ConfigurationError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.local_service import LocalServiceKind
from app.db.models.ml_service_call import MLCallStatus, MLServiceCall, TranscriptionSurface
from app.db.models.organization import DictationEngine, Organization
from app.repositories import ml_service_call_repo
from app.repositories import organization as organization_repo
from app.repositories.ml_service_call import CallFilters, UsageSummary
from app.services import speech_to_text, transcription, transcription_usage
from app.services.local_service import LocalServiceService
from app.services.ml import parsing, pii
from app.services.ml.catalog import SERVICE_CATALOG, MLServiceEntry
from app.services.speech_to_text import RecordingFormat
from app.services.speech_to_text_settings import SpeechToTextSettingsService
from app.services.transcription import Recording, TranscriptionService
from app.services.transcription_usage import TranscriptionCall

logger = logging.getLogger(__name__)

DICTATION_BYTES_PER_SECOND = 32_768
"""Bytes per second of recording the dictation cap allows.

Double what the composer records at (128 kbps Opus is 16 KB/s), so a browser
that encodes a little fatter than asked is not refused, while a caller posting
straight to the endpoint cannot buy an hour of transcription with one request.
The WAV the composer records for Mistral (16 kHz mono 16-bit PCM) is 32,000
bytes a second plus a 44-byte header, so it fits under the same cap.
"""

DICTATION_TYPES = frozenset({"audio/webm", "audio/ogg", "audio/mp4", "audio/wav"})
"""What the composer records, by `transcription.recording_type`.

The first three are what browsers' `MediaRecorder` produces; WAV is what the
composer builds itself for a provider that documents neither WebM nor Opus
(Mistral). A `Blob` in a `FormData` arrives named `blob`, so the name the
provider is sent comes from the type (`transcription.RECORDING_EXTENSIONS`).
Narrower than that table on purpose: an MP3 is not something the composer
records, so one posted here is not a dictation.
"""


@dataclass(frozen=True)
class ServerDictation:
    """Whether a recording for one agent would reach a provider, and in what format."""

    available: bool
    provider: str | None
    format: RecordingFormat


@dataclass(frozen=True)
class DictationStatus:
    """What the composer needs before offering the microphone for one agent."""

    engine: DictationEngine
    ready: bool
    server_available: bool
    max_seconds: int
    provider: str | None
    format: RecordingFormat


@dataclass(frozen=True)
class Transcript:
    """What was said, and which engine said so."""

    text: str
    provider: str
    model: str


class MLService:
    """The standalone ML service surface, and the record of what it was asked."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def catalog() -> tuple[MLServiceEntry, ...]:
        """The coverage matrix: every required family and how far it is delivered."""
        return SERVICE_CATALOG

    async def analyze_document(
        self,
        ctx: AuthContext,
        *,
        content: bytes,
        filename: str,
        parser: str,
        chunk_size: int,
        chunk_overlap: int,
        chunking_strategy: str,
    ) -> parsing.ParsedDocument:
        """Read a document's structure and prepare its content (FA-070)."""
        started = time.monotonic()
        try:
            _refuse_oversized(content)
            document = await parsing.analyze(
                content,
                filename,
                parser=parser,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                chunking_strategy=chunking_strategy,
            )
        except AppException as exc:
            await self._record_failure(
                ctx,
                "document_analysis",
                exc=exc,
                input_bytes=len(content),
                started=started,
            )
            raise
        await self._record(
            ctx,
            "document_analysis",
            input_bytes=len(content),
            units=len(document.pages),
            unit="pages",
            started=started,
        )
        return document

    async def recognise_document(
        self,
        ctx: AuthContext,
        *,
        content: bytes,
        filename: str,
        language: str,
        ocr_service_id: UUID | None,
    ) -> parsing.ParsedDocument:
        """Recognise the text on a scanned document's pages (FA-071)."""
        started = time.monotonic()
        try:
            _refuse_oversized(content)
            server = await self._ocr_server(ctx, ocr_service_id)
            document = await parsing.recognise(
                content, filename, language=language, ocr_server_url=server
            )
        except AppException as exc:
            await self._record_failure(
                ctx, "ocr", exc=exc, input_bytes=len(content), started=started
            )
            raise
        await self._record(
            ctx,
            "ocr",
            input_bytes=len(content),
            units=len(document.pages),
            unit="pages",
            started=started,
        )
        return document

    async def transcribe(
        self,
        ctx: AuthContext,
        *,
        content: bytes,
        filename: str,
        mime_type: str,
        provider: str | None,
        model: str | None,
    ) -> Transcript:
        """Turn a recording into text on the organization's own engine (FA-072).

        Raises:
            BadRequestError: If the deployment offers no transcription at all,
                the provider and model named are not a pair it offers, the
                recording is over the size limit (`reason="too_large"`), or the
                engine heard nothing in it (`reason="empty"`).
            ConfigurationError: `reason="not_configured"` - the organization has
                no usable credential for the provider.
            ExternalServiceError: `reason="provider_error"` or `reason="timeout"`.
                The client's own text stays in the log, where it cannot carry a key.
        """
        started = time.monotonic()
        call = TranscriptionCall(
            organization_id=ctx.organization_id,
            requested_by_user_id=ctx.subject_id,
            surface="api",
            provider=None,
            model=None,
        )
        try:
            _refuse_oversized(content, ceiling=transcription.MAX_BYTES)
            chosen = self._transcription_choice(provider, model)
            call = replace(call, provider=chosen[0], model=chosen[1])
            result = await TranscriptionService(self.db).transcribe(
                Recording(content=content, filename=filename, mime_type=mime_type),
                organization_id=ctx.organization_id,
                provider=chosen[0],
                model=chosen[1],
            )
        except AppException as exc:
            await self._record_transcription_failure(
                call, exc=exc, input_bytes=len(content), audio_seconds=None, started=started
            )
            raise
        await transcription_usage.record(
            self.db,
            call,
            input_bytes=len(content),
            audio_seconds=result.audio_seconds,
            duration_ms=_elapsed_ms(started),
        )
        return Transcript(text=result.text, provider=chosen[0], model=chosen[1])

    async def dictate(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        content: bytes,
        mime_type: str,
        reported_seconds: float | None = None,
    ) -> str:
        """Transcribe a composer recording for one agent (#1797).

        The caller has already proven run access on `agent`. The gate is the
        organization's engine for `/chat`: anything but `server` refuses as
        `not_configured`. Everything after the gate is `transcribe_dictation`,
        which the hosted page and the widget share.

        Raises:
            ConfigurationError: `reason="not_configured"` - the engine is not
                `server`, no pair resolves, or the provider has no credential here.
            BadRequestError: `reason` `empty`, `unsupported_type` or `too_large`.
            ExternalServiceError: `reason` `provider_error` or `timeout`.
        """
        org = await organization_repo.get_by_id(self.db, ctx.organization_id)
        return await self.transcribe_dictation(
            TranscriptionCall(
                organization_id=ctx.organization_id,
                requested_by_user_id=ctx.subject_id,
                surface="chat",
                provider=None,
                model=None,
                agent_id=agent.id,
            ),
            organization=org if org is not None and org.chat_dictation == "server" else None,
            agent=agent,
            content=content,
            mime_type=mime_type,
            reported_seconds=reported_seconds,
        )

    async def transcribe_dictation(
        self,
        call: TranscriptionCall,
        *,
        organization: Organization | None,
        agent: Agent,
        content: bytes,
        mime_type: str,
        reported_seconds: float | None = None,
    ) -> str:
        """Transcribe one dictation for `agent`, past whichever gate its surface has.

        **No `AuthContext`, on purpose.** The composer has a signed-in member; the
        hosted page and the widget have a stranger, and nothing about them belongs
        in a context. So the caller decides whether this surface may dictate at
        all - the organization's `/chat` engine for the composer, the embed's own
        `dictation` setting for a page or a widget - and says who the call is
        attributed to in `call`. `organization` is `None` when that gate is shut,
        and the refusal is then the same `not_configured` either way. Usage is
        never attributed to whoever published an embed: a visitor's dictation is
        the agent's and the surface's, with no requester.

        The provider, model and language resolve through
        `speech_to_text_settings` - the agent's published override first, then
        the organization. Nothing is kept but the usage record: the audio is
        discarded when this returns, and the text goes back in the response only.

        The byte cap is the organization's longest dictation at
        `DICTATION_BYTES_PER_SECOND`, never above what transcription accepts.

        `reported_seconds` is the length the browser says it recorded. It is
        **client-reported** and used only where the provider states no length
        of its own (`gpt-4o-transcribe` does not), and only after clamping to
        what the byte cap stands for - so a caller posting straight to the
        endpoint can inflate its own usage figure by at most the organization's
        longest dictation, never by an hour.

        Raises:
            ConfigurationError: `reason="not_configured"` - the gate is shut, no
                pair resolves, or the provider has no credential here.
            BadRequestError: `reason` `empty`, `unsupported_type` or `too_large`.
            ExternalServiceError: `reason` `provider_error` or `timeout`.
        """
        started = time.monotonic()
        reported: float | None = None
        try:
            resolved = (
                await SpeechToTextSettingsService(self.db).for_agent(agent)
                if organization is not None
                else None
            )
            if organization is None or resolved is None:
                raise ConfigurationError(
                    message="Server dictation is not set up for this agent.",
                    details={"reason": "not_configured"},
                )
            call = replace(call, provider=resolved.provider, model=resolved.model)
            if not content:
                raise BadRequestError(
                    message="The recording is empty.", details={"reason": "empty"}
                )
            base_type = transcription.recording_type(mime_type)
            if base_type not in DICTATION_TYPES:
                raise refused_field(
                    "file",
                    "Dictation accepts WebM, Ogg, MP4 or WAV audio.",
                    reason="unsupported_type",
                )
            cap = min(
                organization.dictation_max_seconds * DICTATION_BYTES_PER_SECOND,
                transcription.MAX_BYTES,
            )
            if reported_seconds is not None:
                reported = min(max(reported_seconds, 0.0), cap / DICTATION_BYTES_PER_SECOND)
            if len(content) > cap:
                raise refused_field(
                    "file",
                    "The recording is longer than this organization's "
                    f"{organization.dictation_max_seconds}-second limit.",
                    reason="too_large",
                )
            result = await TranscriptionService(self.db).transcribe(
                Recording(
                    content=content,
                    filename=f"recording.{transcription.RECORDING_EXTENSIONS[base_type]}",
                    mime_type=base_type,
                ),
                organization_id=call.organization_id,
                provider=resolved.provider,
                model=resolved.model,
                language=resolved.language,
            )
        except AppException as exc:
            await self._record_transcription_failure(
                call,
                exc=exc,
                input_bytes=len(content),
                audio_seconds=reported,
                started=started,
            )
            raise
        await transcription_usage.record(
            self.db,
            call,
            input_bytes=len(content),
            audio_seconds=(result.audio_seconds if result.audio_seconds is not None else reported),
            duration_ms=_elapsed_ms(started),
        )
        return result.text

    async def dictation_status(self, ctx: AuthContext, *, agent: Agent) -> DictationStatus:
        """Whether the composer can dictate to this agent, and on which provider.

        Read before the microphone is offered, so a recording is not made only
        to be refused. `ready` is the organization's `/chat` engine being
        `server` *and* `server_dictation` saying a provider is there to reach;
        `server_available` is the second half alone, which is what the embed
        form asks - a hosted page and a widget have a switch of their own and
        the `/chat` engine does not gate them.

        An agent with nothing published answers from the organization alone,
        as dictation itself would - never a refusal.
        """
        org = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if org is None:
            raise NotFoundError(
                message="Organization not found",
                details={"organization_id": ctx.organization_id},
            )
        server = await self.server_dictation(agent)
        return DictationStatus(
            engine=org.chat_dictation,
            ready=org.chat_dictation == "server" and server.available,
            server_available=server.available,
            max_seconds=org.dictation_max_seconds,
            provider=server.provider,
            format=server.format,
        )

    async def server_dictation(self, agent: Agent) -> ServerDictation:
        """Whether a recording for `agent` would reach a provider, whatever the gate.

        `available` needs a pair that resolves for this agent, the catalog still
        offering it, and the organization holding a credential for its provider -
        checked for existence, never opened. Configured, not proven: a revoked
        key fails on the first recording. The provider and the format are
        returned whether or not it is available, because a browser records in
        the format that provider accepts.

        No `AuthContext`: the embed service asks this for an anonymous visitor's
        page, so the organization is the agent's own and never a caller's.
        """
        resolved = await SpeechToTextSettingsService(self.db).for_agent(agent)
        provider = resolved.provider if resolved is not None else None
        available = (
            resolved is not None
            and speech_to_text.is_offered(resolved.provider, resolved.model)
            and resolved.provider
            in await TranscriptionService(self.db).credentialed_providers(agent.organization_id)
        )
        return ServerDictation(
            available=available,
            provider=provider,
            format=speech_to_text.recording_format(provider),
        )

    async def speech_to_text_credentials(self, ctx: AuthContext) -> frozenset[str]:
        """Which transcription providers this organization holds a credential for.

        Existence only, never opened - see `TranscriptionService.credentialed_providers`.
        """
        return await TranscriptionService(self.db).credentialed_providers(ctx.organization_id)

    async def detect_personal_data(
        self, ctx: AuthContext, *, text: str, categories: Sequence[str] | None
    ) -> pii.PiiReport:
        """Count the personal data in a piece of text and redact it (FA-073)."""
        started = time.monotonic()
        try:
            report = pii.scan(text, categories=categories)
        except AppException as exc:
            await self._record_failure(
                ctx, "pii_detection", exc=exc, input_bytes=len(text.encode()), started=started
            )
            raise
        await self._record(
            ctx,
            "pii_detection",
            input_bytes=len(text.encode()),
            units=len(text),
            unit="characters",
            started=started,
        )
        return report

    async def call_record(self, ctx: AuthContext, call_id: UUID) -> MLServiceCall:
        """One call's record, or a 404 for a call another tenant made."""
        row = await ml_service_call_repo.get(self.db, call_id, organization_id=ctx.organization_id)
        if row is None:
            raise NotFoundError(message="ML service call not found", details={"call_id": call_id})
        return row

    async def call_records(
        self,
        ctx: AuthContext,
        *,
        service: str | None,
        skip: int,
        limit: int,
        agent_id: UUID | None = None,
        channel_bot_id: UUID | None = None,
        surface: TranscriptionSurface | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[MLServiceCall], int]:
        """A page of this organization's calls, and how many there are.

        The filters narrow inside the caller's organization and never widen it:
        another tenant's agent or bot id matches nothing, the same as an id that
        does not exist. `since` is inclusive and `until` exclusive.
        """
        filters = CallFilters(
            service=service,
            agent_id=agent_id,
            channel_bot_id=channel_bot_id,
            surface=surface,
            since=since,
            until=until,
        )
        rows = await ml_service_call_repo.list_for(
            self.db,
            organization_id=ctx.organization_id,
            filters=filters,
            skip=skip,
            limit=limit,
        )
        total = await ml_service_call_repo.count_for(
            self.db, organization_id=ctx.organization_id, filters=filters
        )
        return rows, total

    async def usage_summary(self, ctx: AuthContext, *, service: str, days: int) -> UsageSummary:
        """This organization's successful `service` calls over the last `days`, added up.

        By agent and by channel bot with their names, which is why the route
        asks for `runs:view` rather than `ml:invoke`: a Member may transcribe,
        but the names of agents and bots they cannot see are not theirs to read.
        """
        return await ml_service_call_repo.summarise(
            self.db,
            organization_id=ctx.organization_id,
            service=service,
            since=datetime.now(UTC) - timedelta(days=days),
        )

    async def _ocr_server(self, ctx: AuthContext, ocr_service_id: UUID | None) -> str | None:
        """The address of the OCR server the caller named, or None for the bundled one.

        Resolved through the service that owns the rows, so the tenant scoping
        is the one every other consumer of these rows gets: an organization sees
        its own and the deployment's, and nothing else.
        """
        if ocr_service_id is None:
            return None
        row = await LocalServiceService(self.db).get_visible(ctx, ocr_service_id)
        if row.kind != LocalServiceKind.OCR.value:
            raise refused_field(
                "ocr_service_id", f"That service is registered for {row.kind}, not for OCR."
            )
        if not row.is_active:
            raise refused_field(
                "ocr_service_id", "That OCR server is turned off; turn it on or name another."
            )
        return row.base_url

    @staticmethod
    def _transcription_choice(provider: str | None, model: str | None) -> tuple[str, str]:
        """The provider and model to transcribe with, refusing a pair nobody serves.

        A caller who names a provider and no model gets *that provider's* first
        model, never the deployment's default pair. Falling back to the default
        when half the choice was made is how a recording meant for a self-hosted
        engine is sent to a vendor instead - the caller said which engine, and
        the only thing they left open was which of its models.
        """
        if provider is None and model is None:
            chosen = speech_to_text.default_choice()
            if chosen is None:
                raise refused_field(
                    "provider",
                    "This deployment offers no transcription provider, so a provider and "
                    "model cannot be defaulted; there is nothing to name.",
                )
            return chosen
        if provider is None:
            raise refused_field(
                "provider",
                "Naming a model needs the provider it belongs to; two providers can "
                "offer the same model id.",
            )
        entry = speech_to_text.by_provider(provider)
        if entry is None:
            raise refused_field("provider", f"{provider} does not transcribe on this deployment.")
        if model is None:
            return provider, entry.models[0].id
        if not speech_to_text.is_offered(provider, model):
            raise refused_field(
                "model", f"{provider} does not offer {model} for transcription here."
            )
        return provider, model

    async def _record(
        self,
        ctx: AuthContext,
        service: str,
        *,
        input_bytes: int,
        units: int,
        unit: str,
        started: float,
    ) -> None:
        """Write the usage record into the caller's own transaction."""
        await ml_service_call_repo.record(
            self.db,
            organization_id=ctx.organization_id,
            requested_by_user_id=ctx.subject_id,
            service=service,
            status=MLCallStatus.SUCCEEDED.value,
            input_bytes=input_bytes,
            units=units,
            unit=unit,
            duration_ms=_elapsed_ms(started),
        )

    async def _record_failure(
        self,
        ctx: AuthContext,
        service: str,
        *,
        exc: AppException,
        input_bytes: int,
        started: float,
    ) -> None:
        """Write a refusal's record, and commit it before the refusal unwinds.

        A refusal rolls the request's transaction back - that is what a refusal
        does - so a row merely added to it would be undone by the very refusal it
        describes, and an operator asking why their integration is failing would
        be told the tenant made no calls at all.

        So this commits deliberately, which is the bargain `AgentRunnerService._run`
        and `SessionService.detect_refresh_reuse` already strike: a service that
        needs a write to outlive its caller's transaction commits it, and says
        why. It is safe here because nothing else is in that transaction - an ML
        call writes its usage record and nothing more, and every one of these
        paths fails before it has written even that.

        **On this session, not a second one.** An earlier version opened
        `get_db_context()`, which checks out a second connection from the pool
        while the request still holds its first; a burst of refusals would then
        have every caller waiting `DB_POOL_TIMEOUT` for a connection their
        neighbours were holding, and the records dropped anyway. One session, one
        connection, no second checkout.

        A failure to write it is logged and swallowed: the caller is owed the
        refusal that actually happened, not a 500 from the bookkeeping.
        """
        stage, reason = transcription_usage.failure_of(exc)
        try:
            await ml_service_call_repo.record(
                self.db,
                organization_id=ctx.organization_id,
                requested_by_user_id=ctx.subject_id,
                service=service,
                status=MLCallStatus.FAILED.value,
                input_bytes=input_bytes,
                units=0,
                unit="",
                duration_ms=_elapsed_ms(started),
                failure_stage=stage,
                failure_reason=reason,
            )
            await self.db.commit()
        except Exception:
            logger.warning(
                "Could not record the failure of an %s call for organization %s",
                service,
                ctx.organization_id,
                exc_info=True,
            )
            await self.db.rollback()

    async def _record_transcription_failure(
        self,
        call: TranscriptionCall,
        *,
        exc: AppException,
        input_bytes: int,
        audio_seconds: float | None,
        started: float,
    ) -> None:
        """A refused transcription's row, with its attribution, committed like any refusal.

        The same bargain as `_record_failure`, and the same session: the row is
        flushed by `transcription_usage.record` and committed here, before the
        refusal rolls the request back. A commit that fails is logged and the
        refusal still reaches the caller.
        """
        await transcription_usage.record(
            self.db,
            call,
            input_bytes=input_bytes,
            audio_seconds=audio_seconds,
            duration_ms=_elapsed_ms(started),
            failure=exc,
        )
        try:
            await self.db.commit()
        except Exception:
            logger.warning(
                "Could not commit the failure of a transcription for organization %s",
                call.organization_id,
                exc_info=True,
            )
            await self.db.rollback()


def _refuse_oversized(content: bytes, *, ceiling: int | None = None) -> None:
    """Refuse a submission over the ML surface's own ceiling.

    Measured here rather than in the route because it is the same ceiling for
    every service on this surface, and because a refusal from inside the call is
    a refusal the usage log records - a caller repeatedly sending files too
    large is exactly the pattern an operator reads that log to find.

    `ceiling` narrows it where the engine behind the service has one of its own.
    Transcription does: its client refuses over 25 MB before the upload, and an
    operator who raised `ML_MAX_UPLOAD_SIZE_MB` above that would otherwise have
    recordings accepted here, refused there, and reported as a 503 about a
    credential - a misleading answer to a question about size.

    The routes read at most this many bytes plus one, so a body larger than the
    ceiling is never fully copied into memory; this is what turns that truncated
    read into the refusal that names the limit.
    """
    limit = settings.ML_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if ceiling is not None:
        limit = min(limit, ceiling)
    if len(content) > limit:
        raise refused_field(
            "file",
            f"This service accepts at most {limit // (1024 * 1024)} MB; "
            "split the document or the recording.",
        )


def _elapsed_ms(started: float) -> int:
    """How long the call took, in whole milliseconds."""
    return int((time.monotonic() - started) * 1000)
