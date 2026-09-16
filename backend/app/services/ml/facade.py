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
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, ExternalServiceError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.local_service import LocalServiceKind
from app.db.models.ml_service_call import MLCallStatus, MLServiceCall
from app.repositories import ml_service_call_repo
from app.services import speech_to_text, transcription
from app.services.local_service import LocalServiceService
from app.services.ml import parsing, pii
from app.services.ml.catalog import SERVICE_CATALOG, MLServiceEntry
from app.services.transcription import Recording, TranscriptionService

logger = logging.getLogger(__name__)


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
                or the provider and model named are not a pair it offers.
            ExternalServiceError: If the engine answered with nothing. The
                organization having no usable credential for the provider is
                the common cause, and the message says so - the client's own
                text stays in the log, where it cannot carry a key.
        """
        started = time.monotonic()
        try:
            _refuse_oversized(content, ceiling=transcription.MAX_BYTES)
            chosen = self._transcription_choice(provider, model)
            text = await TranscriptionService(self.db).transcribe(
                Recording(content=content, filename=filename, mime_type=mime_type),
                organization_id=ctx.organization_id,
                provider=chosen[0],
                model=chosen[1],
            )
            if text is None:
                raise ExternalServiceError(
                    message=(
                        "The transcription engine returned nothing. Check that this "
                        "organization has a usable credential for the provider and that "
                        "the recording is within the size limit."
                    ),
                    details={"provider": chosen[0], "model": chosen[1], "stage": "engine"},
                )
        except AppException as exc:
            await self._record_failure(
                ctx, "speech_to_text", exc=exc, input_bytes=len(content), started=started
            )
            raise
        await self._record(
            ctx,
            "speech_to_text",
            input_bytes=len(content),
            units=len(text),
            unit="characters",
            started=started,
        )
        return Transcript(text=text, provider=chosen[0], model=chosen[1])

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
        self, ctx: AuthContext, *, service: str | None, skip: int, limit: int
    ) -> tuple[list[MLServiceCall], int]:
        """A page of this organization's calls, and how many there are."""
        rows = await ml_service_call_repo.list_for(
            self.db,
            organization_id=ctx.organization_id,
            service=service,
            skip=skip,
            limit=limit,
        )
        total = await ml_service_call_repo.count_for(
            self.db, organization_id=ctx.organization_id, service=service
        )
        return rows, total

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
        reason = exc.message[:512]
        stage = str(exc.details.get("stage", "input")) if exc.details else "input"
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
                failure_stage=stage[:32],
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
