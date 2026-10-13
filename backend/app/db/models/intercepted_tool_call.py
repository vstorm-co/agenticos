"""A tool call an isolated run answered without executing it.

An eval runs the agent for real, so its tools would run for real: an agent that
sends e-mail would send one per case. An isolated run executes only what is safe
- reads, and calls routed to an environment's test connections - and every
other call stops at the guard (`app/agents/isolation.py`). Stopping it must not
lose it: what the agent *meant* to do is the half of an eval that trajectory
scoring judges, so each one is written down here with its arguments.

A table of its own rather than `tool_calls` rows: those hang off a message, and
an eval run is not obliged to have a conversation. Rather than a column on
`agent_runs` for the reason `run_manifests` gives - it is the most-listed table
in the product and none of its listings ask this.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base, TimestampMixin


class InterceptionOutcome(enum.StrEnum):
    """Why a call was answered by the guard rather than by the tool.

    Attributes:
        BLOCKED: Not executed, for the `InterceptionReason` beside it. Its
            intended arguments are the record.
        REPLAYED: Answered from the original run's recording - the same tool,
            the same arguments, the same occurrence.
        DIVERGENT: The run was answering from a recording and this call had no
            match in it. Not executed; the divergence is a finding.
    """

    BLOCKED = "blocked"
    REPLAYED = "replayed"
    DIVERGENT = "divergent"


class InterceptionReason(enum.StrEnum):
    """Why a blocked call was blocked.

    Attributes:
        WRITES: The tool changes something outside the run and the environment
            gives it no test connection.
        NEEDS_APPROVAL: The tool would have run, but the agent gates it behind an
            approval and an isolated run has nobody to ask.
    """

    WRITES = "writes"
    NEEDS_APPROVAL = "needs_approval"


class InterceptedToolCall(Base, TimestampMixin):
    """One call an isolated run did not execute, in the order it was made."""

    __tablename__ = "intercepted_tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The agent of the run's tree that made the call. Null for an inline
    # specialist, which has no row of its own.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # `capability:<capability>.<tool>`, which survives a rename, or
    # `tool:<name>` for an MCP or framework tool.
    tool_id: Mapped[str] = mapped_column(String(256), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # Set on a blocked call only: a replayed or divergent one needs no reason.
    reason: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('blocked', 'replayed', 'divergent')",
            name="ck_intercepted_tool_call_outcome",
        ),
        CheckConstraint(
            "(outcome = 'blocked' AND reason IS NOT NULL AND reason IN ('writes', 'needs_approval')) "
            "OR (outcome <> 'blocked' AND reason IS NULL)",
            name="ck_intercepted_tool_call_reason",
        ),
        Index("ix_intercepted_tool_calls_run_sequence", "run_id", "sequence"),
    )

    def __repr__(self) -> str:
        return (
            f"<InterceptedToolCall(id={self.id}, run_id={self.run_id}, "
            f"tool_name={self.tool_name}, outcome={self.outcome})>"
        )
