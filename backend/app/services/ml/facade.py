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
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.local_service import LocalServiceKind
from app.db.models.ml_service_call import MLCallStatus, MLServiceCall, TranscriptionSurface
from app.db.models.organization import DictationEngine, Organization
from app.repositories import ml_service_call_repo
from app.repositories import organization as organization_repo
from app.repositories.ml_service_call import CallFilters, UsageSummary
from app.services import speech_to_text, transcription, transcription_usage
from app.services.deployment_settings import DeploymentSettingsService
from app.services.local_service import LocalServiceService
from app.services.ml import audio_duration, parsing, pcm_wav, pii
from app.services.ml.catalog import SERVICE_CATALOG, MLServiceEntry
from app.services.speech_to_text import RecordingFormat
from app.services.speech_to_text_settings import SpeechToTextSettingsService
from app.services.transcription import Recording, TranscriptionService
from app.services.transcription_usage import TranscriptionCall

logger = logging.getLogger(__name__)

DICTATION_BYTES_PER_SECOND = pcm_wav.BYTES_PER_SECOND
"""Bytes per second of recording the dictation byte cap allows: 32,000.

What dictation's own format holds - 16 kHz mono 16-bit PCM is exactly this
many bytes of samples a second - so for a WAV recording the cap and the length
are the same limit, read twice. The length is what is refused on, from the
samples counted (`pcm_wav`); the cap is the cheap check in front of it.

**For compressed audio it is an outer bound only.** Where the deployment
accepts WebM, Ogg and MP4 (`DeploymentSettings.dictation_compressed_audio`),
32 kbps Opus is 4,000 bytes a second, so a browser's recording fits with room
to spare - and Opus at a script's lowest bitrate fits one to three hours into
the same bytes. Their length is read from the file's own header
(`audio_duration`), which a file built by hand can understate; this cap is what
still holds then, and for a recording whose length is unknown where the surface
accepts one.
"""

DICTATION_HEADER_ALLOWANCE = 4_096
"""Bytes the cap allows beyond the audio itself, for the container around it.

A browser's WAV header is 44 bytes; the rest is room for a chunk a writer
adds, which `pcm_wav` steps over and the provider is never sent.
"""

DICTATION_GRACE_SECONDS = 3
"""How far past `dictation_max_seconds` a measured recording may run.

The composer stops a recording on a once-a-second tick of the browser's clock,
so one that stopped at the limit is up to a second over it, and a throttled tab
ticks late. Refusing those would refuse exactly the recordings the limit
stopped for the person.
"""

DICTATION_PCM_TYPES = frozenset({"audio/wav"})
"""What dictation accepts by default, by `transcription.recording_type`.

WAV holding 16 kHz mono 16-bit PCM, which the composer, the hosted page and the
widget build themselves from the microphone's samples: the one format whose
length is its size. Every other kind of WAV is refused by `pcm_wav`.
"""

DICTATION_COMPRESSED_TYPES = frozenset({"audio/webm", "audio/ogg", "audio/mp4"})
"""What dictation also accepts once the deployment has turned compressed audio on.

What browsers' `MediaRecorder` produces. A `Blob` in a `FormData` arrives named
`blob`, so the name the provider is sent comes from the type
(`transcription.RECORDING_EXTENSIONS`). Narrower than that table on purpose: an
MP3 is not something a browser records here, so one posted is not a dictation.
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
        which the hosted page and the widget share. A compressed recording
        whose length cannot be read - where the deployment accepts compressed
        audio at all - is accepted here, under the byte cap: the caller is a
        signed-in member on their own rate limit, and refusing would refuse a
        browser whose container this does not read.

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
            accept_unmeasured=True,
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
        accept_unmeasured: bool,
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

        **Raw PCM unless the deployment says otherwise.** A dictation is WAV
        holding 16 kHz mono 16-bit PCM (`pcm_wav`), whose length is its byte
        count: the samples are counted, a recording longer than
        `dictation_max_seconds` (plus `DICTATION_GRACE_SECONDS`) is refused as
        `too_large` before the provider is called, and the provider is sent
        those samples behind a header built here - never the caller's header,
        nor any other chunk the file carried. Any other WAV is refused as
        `unsupported_type`.

        Where the deployment accepts compressed audio
        (`DeploymentSettingsService.accepts_compressed_dictation`), WebM, Ogg
        and MP4 are accepted too, and their length is read from the file's own
        header (`audio_duration`) - the file's word for it, which a file built
        by hand can understate, so the byte cap is then what bounds it. A
        length that cannot be read is the caller's to decide:
        `accept_unmeasured` lets it through under the byte cap alone, which is
        what the console does for a member; otherwise it is refused as
        `unsupported_type`, which is what a public page does for a stranger,
        whose spend nothing else bounds. Off, these types are refused as
        `unsupported_type` before anything is read.

        The byte cap - the longest dictation plus its grace at
        `DICTATION_BYTES_PER_SECOND`, with `DICTATION_HEADER_ALLOWANCE` for
        the container, never above what transcription accepts - is checked
        first in both, because it is free.

        The usage row's length is the measured one, then the provider's own
        figure, then `reported_seconds` - the length the browser says it
        recorded. For PCM it is always the measured one, exactly. The last is
        **client-reported**, used only where nothing else states a length,
        and clamped to the organization's longest dictation - so a caller
        posting straight to the endpoint can inflate its own usage figure by
        at most that, never by an hour.

        Raises:
            ConfigurationError: `reason="not_configured"` - the gate is shut, no
                pair resolves, or the provider has no credential here.
            BadRequestError: `reason` `empty`, `unsupported_type` (a type or a
                WAV this does not accept, or a compressed length that cannot
                be read, unless `accept_unmeasured`) or `too_large`, the latter
                with `limit_seconds` in its details.
            ExternalServiceError: `reason` `provider_error` or `timeout`.
        """
        started = time.monotonic()
        reported: float | None = None
        measured: float | None = None
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
            compressed = await DeploymentSettingsService(self.db).accepts_compressed_dictation()
            accepted = (
                DICTATION_PCM_TYPES | DICTATION_COMPRESSED_TYPES
                if compressed
                else DICTATION_PCM_TYPES
            )
            base_type = transcription.recording_type(mime_type)
            if base_type not in accepted:
                raise refused_field(
                    "file",
                    _ACCEPTED_AUDIO[compressed],
                    reason="unsupported_type",
                    accepted=sorted(accepted),
                )
            limit = organization.dictation_max_seconds
            cap = min(
                (limit + DICTATION_GRACE_SECONDS) * DICTATION_BYTES_PER_SECOND
                + DICTATION_HEADER_ALLOWANCE,
                transcription.MAX_BYTES,
            )
            if reported_seconds is not None:
                reported = min(max(reported_seconds, 0.0), float(limit))
            too_long = refused_field(
                "file",
                f"The recording is longer than this organization's {limit}-second limit.",
                reason="too_large",
                limit_seconds=limit,
            )
            if len(content) > cap:
                raise too_long
            if base_type in DICTATION_PCM_TYPES:
                recording, measured = _pcm_recording(content)
            else:
                measured = audio_duration.measure(content)
                if measured is None and not accept_unmeasured:
                    raise refused_field(
                        "file",
                        "The recording's length could not be read. Dictation accepts WebM, "
                        "Ogg or MP4 audio as a browser records it.",
                        reason="unsupported_type",
                    )
                recording = Recording(
                    content=content,
                    filename=f"recording.{transcription.RECORDING_EXTENSIONS[base_type]}",
                    mime_type=base_type,
                )
            if measured is not None and measured > limit + DICTATION_GRACE_SECONDS:
                raise too_long
            result = await TranscriptionService(self.db).transcribe(
                recording,
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
                audio_seconds=measured if measured is not None else reported,
                started=started,
            )
            raise
        await transcription_usage.record(
            self.db,
            call,
            input_bytes=len(content),
            audio_seconds=_first_known(measured, result.audio_seconds, reported),
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
        as dictation itself would - never a refusal. An archived agent is never
        `ready`: nobody chats with it, so a microphone offered for it would
        only spend the organization's provider credit on text with nowhere to go.
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
            ready=(
                org.chat_dictation == "server"
                and server.available
                and agent.status != AgentStatus.ARCHIVED.value
            ),
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
        the format they say.

        The format is `wav` - 16 kHz mono 16-bit PCM - unless the deployment
        accepts compressed audio *and* the catalog says this provider takes
        what `MediaRecorder` makes; Mistral is `wav` either way.

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
        compressed = await DeploymentSettingsService(self.db).accepts_compressed_dictation()
        return ServerDictation(
            available=available,
            provider=provider,
            format=speech_to_text.recording_format(provider) if compressed else "wav",
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

        Filtering by agent, bot or surface needs `runs:view`, as the summary
        does (`sees_attribution`): a count of calls per agent id is the
        summary's breakdown asked for one row at a time.

        Raises:
            AuthorizationError: An attribution filter without `runs:view`.
        """
        if (
            agent_id is not None or channel_bot_id is not None or surface is not None
        ) and not self.sees_attribution(ctx):
            raise AuthorizationError(
                message="Filtering calls by agent, bot or surface needs runs:view",
                details={"required": [Perm.RUNS_VIEW.value]},
            )
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

    @staticmethod
    def sees_attribution(ctx: AuthContext) -> bool:
        """Whether this caller may read which agent, bot and surface a call came from.

        `runs:view`, the summary's gate. `ml:invoke` - every Member - lets a
        caller use the services and read the log of calls, which before #1797
        named nobody; the attribution added since is the organization's map
        of which agents and bots transcribe, and is answered to the people who
        may read runs. Without it a call record comes back as it did before.
        """
        return ctx.has(Perm.RUNS_VIEW)

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


_ACCEPTED_AUDIO: dict[bool, str] = {
    False: "Dictation accepts WAV audio as 16 kHz mono 16-bit PCM.",
    True: "Dictation accepts WebM, Ogg or MP4 audio, or WAV as 16 kHz mono 16-bit PCM.",
}
"""What a refused type is told, by whether the deployment accepts compressed audio."""


def _pcm_recording(content: bytes) -> tuple[Recording, float]:
    """A dictation WAV as the provider is sent it, and its exact length in seconds.

    The samples behind a header built by `pcm_wav.wrap`, so the provider is
    sent what was counted and nothing the caller's header said.

    Raises:
        BadRequestError: `unsupported_type` for anything but 16 kHz mono 16-bit
            PCM in a well-formed WAV, `empty` for one holding no samples.
    """
    pcm = pcm_wav.samples(content)
    if pcm is None:
        raise refused_field("file", _ACCEPTED_AUDIO[False], reason="unsupported_type")
    if not pcm:
        raise BadRequestError(message="The recording is empty.", details={"reason": "empty"})
    return (
        Recording(content=pcm_wav.wrap(pcm), filename="recording.wav", mime_type="audio/wav"),
        len(pcm) / DICTATION_BYTES_PER_SECOND,
    )


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


def _first_known(*figures: float | None) -> float | None:
    """The first length somebody stated, in the order the caller trusts them."""
    return next((figure for figure in figures if figure is not None), None)


def _elapsed_ms(started: float) -> int:
    """How long the call took, in whole milliseconds."""
    return int((time.monotonic() - started) * 1000)
