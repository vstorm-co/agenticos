"""A remote sandbox still to be destroyed after the rows naming it were deleted."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PendingSandboxDestroy(Base, TimestampMixin):
    """A tombstone for a sandbox whose conversation or project is gone (#2209).

    Deleting a conversation or a project destroys its remote sandboxes once the
    deletion commits - never before, or a rollback would restore rows naming
    files that no longer exist. The rows that named those sandboxes go in the
    same transaction, so a destroy that then fails used to leave nothing
    behind that knew the sandbox existed. A `sandboxd` container has its TTL
    behind it; a Daytona sandbox has nothing, and the organization paid for it
    until somebody noticed.

    So the deleting transaction writes one of these, the destroy removes it once
    the provider confirms, and a sweep retries what is left with a growing
    pause between attempts. The sandbox is named the way the workspace opened
    it - the connection and the ref id - which is all a destroy needs.

    Both foreign keys cascade, for an organization that is deleted with
    everything in it. A connection on its own is not deleted while it holds
    tombstones - `SandboxConnectionService.delete` refuses - since these rows
    are the only record of sandboxes the provider may still be billing for.
    """

    __tablename__ = "pending_sandbox_destroys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Not CASCADE (#2250): a tombstone written by a conversation deleted while the
    # connection was being deleted went with it, and with it the only record of a
    # sandbox still billed on the provider. NO ACTION is checked at the end of the
    # statement, so an organization's purge, which cascades to both, still works.
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sandbox_connections.id"),
        nullable=False,
        index=True,
    )
    ref_id: Mapped[str] = mapped_column(String(255), nullable=False)
    """What the session was opened under: its session id, or the scope key."""
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    """The workspace's scope key, which names the sandbox on a Daytona connection."""
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<PendingSandboxDestroy(id={self.id}, connection_id={self.connection_id}, "
            f"ref_id={self.ref_id}, attempts={self.attempts})>"
        )
