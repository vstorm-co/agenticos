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
characters for a scan, bytes for a recording - not money. The delivered services
either run on the operator's own machines, where there is no vendor price to
record, or on the organization's own provider account, which bills it directly;
inventing a figure for either would put a number in a report that nobody can
reconcile against an invoice.
"""

import uuid
from enum import StrEnum

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
    """What `units` counts: `pages`, `characters`, `bytes`. Empty on a failure,
    where nothing was produced to count."""

    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<MLServiceCall(service={self.service}, status={self.status})>"
