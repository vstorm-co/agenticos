"""One call to an ML service: who made it, what it cost the host, how it ended.

FA-069 asks for the ML services to carry logging and usage reporting the way the
rest of the platform does, and the platform's existing ledgers do not reach
these calls: `agent_runs` records what a run spent and `ingestion_spend` what
indexing a document cost, and a caller who parses a PDF without starting a run
appears in neither. This table is that record.

**It holds no content.** The result of an ML call is returned to the caller and
not retained - a document parsed here is not stored, and the text a caller sent
to be scanned for personal data is the last thing that should be kept in a table
nobody thought of as a document store. So a row is the shape of the call: which
service, whose organization, how much went in, how long it took, and how it
ended. Reading `docs/data-protection.md` and finding a new home for tenant
content is exactly what this design avoids.

**Usage is counted in the unit the service works in.** Pages for a parse,
characters for a scan, seconds of audio for a recording - not money. The delivered services
either run on the operator's own machines, where there is no vendor price to
record, or on the organization's own provider account, which bills it directly;
inventing a figure for either would put a number in a report that nobody can
reconcile against an invoice.

**A transcription also says where it came from** (#1797): which provider and
model heard it, the surface it arrived on, and the agent and channel bot it was
for. Speech to text is reached from three places - this API, dictation in
`/chat` and a channel bot's voice notes - and "how much did we transcribe, and
for whom" is the question an organization asks of it. The columns are null for
every other service and for rows written before them.
"""

import uuid
from enum import StrEnum
from typing import Literal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MLCallStatus(StrEnum):
    """How a call ended.

    Two values, because execution is synchronous: the row is written once the
    service has answered or refused, so there is no moment at which a committed
    row is still running. A queued mode would add its own states here, and the
    column is a string rather than a database enum so that it can.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"


TranscriptionSurface = Literal["chat", "channel", "api", "hosted", "widget"]
"""Where a transcription arrived: dictation in `/chat`, a channel bot's voice
note, `POST /ml/audio/transcriptions`, or a visitor dictating on a hosted page or
in a website widget. A string column rather than an enum, which is how the last
two joined without a migration."""


class MLServiceCall(Base, TimestampMixin):
    """The record of one ML service call, for the tenant that made it."""

    __tablename__ = "ml_service_calls"
    __table_args__ = (
        CheckConstraint("status IN ('succeeded', 'failed')", name="ck_ml_service_calls_status"),
        Index("ix_ml_service_calls_org_created", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    """Whose call this was. Not nullable: every ML endpoint is reached with an
    organization header, and a usage report that silently drops rows nobody
    claims would under-report the tenant that made them."""

    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    """SET NULL rather than CASCADE: a person leaving does not unmake the call
    their organization was billed for."""

    service: Mapped[str] = mapped_column(String(32), nullable=False)
    """The catalog id from `app/services/ml/catalog.py`."""

    status: Mapped[str] = mapped_column(String(16), nullable=False)

    failure_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """Which part gave way - `input`, `parse`, `engine`, `credential`. Null on success."""

    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    """A controlled sentence about the call, never an engine's own text: this
    column is read back by everyone in the organization who can see the log."""

    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    """What `units` counts: `pages`, `characters`, `seconds`. Empty on a failure,
    where nothing was produced to count.

    A successful transcription counts `seconds` of audio, rounded up, and `0`
    when nobody reported the length (`audio_ms` is null) - so a summary can say
    how many recordings it could not measure instead of reading them as silence."""

    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """How long the call took to answer - processing time, not audio length."""

    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """The transcription provider the recording was sent to, where one was chosen."""

    model: Mapped[str | None] = mapped_column(String(255), nullable=True)

    surface: Mapped[TranscriptionSurface | None] = mapped_column(String(16), nullable=True)
    """A `TranscriptionSurface`; null for the other services."""

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The agent a dictation was for, or the agent a channel bot serves. SET NULL
    for the same reason as the requester: deleting an agent does not unmake what
    was transcribed for it."""

    channel_bot_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channel_bots.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The bot a voice note arrived on."""

    audio_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """How long the recording was, in milliseconds, or null where nobody said.

    The first known of: the provider's own answer (`whisper-1`, Groq's verbose
    answer, Mistral), the platform's metadata (Telegram, Slack), and for a
    dictation the length the browser reports. Not measured here: decoding audio
    needs a library the image does not carry."""

    def __repr__(self) -> str:
        return f"<MLServiceCall(service={self.service}, status={self.status})>"
