"""What an agent did in a sandbox, recorded on our side of the wire.

The sandbox service keeps its own log and it is a **200-entry ring buffer in that
process's memory** (`_EVENT_HISTORY`). Its `after` parameter is a polling cursor,
not a page - so what the buffer dropped cannot be asked for, a conversation worked
in all day has lost its morning, and restarting `sandboxd` loses every log on the
host. Nothing outside that process ever saw the entries, which means there was no
audit of what an agent did in a sandbox that outlived the service's uptime
(agenticos#1061).

Every workspace tool call already passes through this application - the run calls
us, we call the service - so the write is ours to make. It is the same shape the
service records, plus the two things the service cannot know: **which agent, and
which run**.

**What is never written here**, and this is the whole reason the log is an audit
rather than a way to read somebody's work: a path and an operation, never a file's
contents and never a command's output. The service is deliberate about that and
the product has to be too, because these rows are readable by everyone who can see
the sandbox.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SandboxOperation(Base, TimestampMixin):
    """One operation an agent performed in one sandbox."""

    __tablename__ = "sandbox_operations"
    __table_args__ = (
        # The read is always "this organization's, newest first", usually narrowed
        # to one session. Both orderings are covered by the same index because the
        # organization is the leading column either way - and it is not optional:
        # one `sandboxd` serves every tenant that registered a connection at its
        # address, so a query without it could read another tenant's log.
        Index(
            "sandbox_operations_org_created_idx",
            "organization_id",
            "created_at",
        ),
        Index(
            "sandbox_operations_session_created_idx",
            "organization_id",
            "session_key",
            "created_at",
        ),
        # A duration is milliseconds and cannot be negative; a negative one would
        # be a clock going backwards, which is worth refusing rather than storing.
        CheckConstraint("duration_ms >= 0", name="ck_sandbox_operation_duration"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Which agent and which run - the two facts the service's own log cannot carry,
    # and the two a person auditing this actually asks for. `SET NULL` on both: the
    # record of what happened must outlive the agent that was deleted afterwards,
    # which is the point of recording it at all.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # The session the operation was performed in, as the service names it. A string
    # rather than an FK to `agent_workspaces`: a run-scoped workspace has no row by
    # design, and the log of one is still worth keeping.
    session_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # What was done and to what. `op` is the backend method (`write`, `exec`,
    # `read_file`); `target` its path or command. Never their contents or output.
    op: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(512), nullable=False)
    # One line about the outcome, written by us: a byte count, "not found", the
    # class of a failure. Never the provider's own message, which for a shell is
    # the command's output and for an HTTP client carries the request (#423).
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<SandboxOperation(id={self.id} op={self.op} session={self.session_key} ok={self.ok})>"
        )


# How long a sandbox's log is kept. A sandbox is reaped after half an hour idle and
# its files may be swept, so a log that outlived the answer to "what happened here"
# by years would be a growing table nobody reads. Thirty days is long enough for
# somebody to come back to an odd bill or an odd file and short enough that the
# sweep is cheap.
OPERATION_RETENTION_DAYS = 30
