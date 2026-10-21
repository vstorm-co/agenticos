"""The usage record of one transcription, wherever it was asked for (#1797).

Speech to text is reached from three surfaces: `POST /ml/audio/transcriptions`,
dictation in the `/chat` composer, and a channel bot's voice notes. The first
two go through the ML facade, which has always written an `ml_service_calls`
row; a voice note went straight to `TranscriptionService` and left none, so an
organization's busiest use of its provider account was the one it could not
see. This is the one writer all three share, so a voice note's row has the same
shape as a dictation's and a summary can add them up.

**No `AuthContext`.** The channel router has none - a voice note arrives from a
platform, not a signed-in request - so the caller states who the call is
attributed to (`TranscriptionCall`) rather than this reading it off a context.

**It flushes and nothing else.** The row goes into the caller's transaction
inside a savepoint, and this never commits or rolls back. The facade commits a
refusal's row itself, as it always has (`MLService._record_failure` says why);
the channel router's turn is committed by the run that follows. A rollback here
would take the router's identity, session and chat-file rows with it, and a
commit would cut the run's transaction in half - so the savepoint is what lets a
row that cannot be written (an agent deleted mid-turn breaks its foreign key)
fail on its own, logged, without costing the sender the transcript or the
caller its answer.

**Only attempts are recorded.** A recording that reached `transcribe` - and so
may have reached the provider and its bill - writes a row, succeeded or failed.
A bot switched off, or a recording with no engine resolving for it, never
attempted anything and writes none.
"""

import logging
import math
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.models.ml_service_call import MLCallStatus, MLServiceCall, TranscriptionSurface
from app.repositories import ml_service_call_repo

logger = logging.getLogger(__name__)

SERVICE = "speech_to_text"
"""The catalog id every transcription is recorded under."""


@dataclass(frozen=True)
class TranscriptionCall:
    """Who and what one transcription is recorded against."""

    organization_id: UUID
    surface: TranscriptionSurface
    provider: str | None
    """`None` where the call was refused before a provider was chosen."""
    model: str | None
    requested_by_user_id: UUID | None = None
    """The person who asked, or - for a voice note - the person the sender's
    platform account is linked to. `None` for an unlinked sender."""
    agent_id: UUID | None = None
    channel_bot_id: UUID | None = None
    secret_id: UUID | None = None
    """The vault key the recording was sent with - the one named next to the
    pair - or `None` where the call was refused before one was chosen."""


def failure_of(exc: AppException) -> tuple[str, str]:
    """`(failure_stage, failure_reason)` for a refusal, as the usage log stores them.

    The stage is what the refusing error named in `details.stage` - `engine` for
    a provider that gave way - and `input` otherwise, since a refusal that names
    no stage was a refusal of what the caller sent. The reason is the
    exception's own controlled message, never an engine's text.
    """
    stage = str(exc.details.get("stage", "input")) if exc.details else "input"
    return stage[:32], exc.message[:512]


async def record(
    db: AsyncSession,
    call: TranscriptionCall,
    *,
    input_bytes: int,
    audio_seconds: float | None,
    duration_ms: int,
    failure: AppException | None = None,
) -> MLServiceCall | None:
    """Write one transcription's row into the caller's transaction, in a savepoint.

    A success counts `seconds` of audio, rounded up so a two-second note is
    never recorded as one, and `0` seconds when nobody reported a length - the
    row still says `seconds`, and `audio_ms` stays null, so a summary can count
    it as unmeasured rather than as silence. A failure counts nothing, as every
    other service's does, but keeps the length where one was known.

    Returns the row, or `None` when it could not be written: a database refusal
    is logged and stays inside the savepoint, because the transcript the caller
    is holding is worth more than its bookkeeping. A length that is not finite -
    a provider's or a chat platform's `inf` or `NaN` - is no length at all, and
    is recorded as unmeasured rather than raised out of the rounding.
    """
    measured = audio_seconds is not None and math.isfinite(audio_seconds)
    audio_ms = max(0, round(audio_seconds * 1000)) if measured else None
    if failure is None:
        status = MLCallStatus.SUCCEEDED.value
        units = 0 if audio_ms is None else math.ceil(audio_ms / 1000)
        unit = "seconds"
        stage: str | None = None
        reason: str | None = None
    else:
        status = MLCallStatus.FAILED.value
        units, unit = 0, ""
        stage, reason = failure_of(failure)
    try:
        async with db.begin_nested():
            return await ml_service_call_repo.record(
                db,
                organization_id=call.organization_id,
                requested_by_user_id=call.requested_by_user_id,
                service=SERVICE,
                status=status,
                input_bytes=input_bytes,
                units=units,
                unit=unit,
                duration_ms=duration_ms,
                failure_stage=stage,
                failure_reason=reason,
                provider=call.provider,
                model=call.model,
                surface=call.surface,
                agent_id=call.agent_id,
                channel_bot_id=call.channel_bot_id,
                secret_id=call.secret_id,
                audio_ms=audio_ms,
            )
    except SQLAlchemyError:
        logger.warning(
            "Could not record a %s transcription for organization %s",
            call.surface,
            call.organization_id,
            exc_info=True,
        )
        return None
