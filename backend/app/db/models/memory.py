"""An agent's own memory - written by the agent, inspected by operators.

Unlike a context file (a human-authored library row bound to many agents and
read-only to the model), a memory file is the agent's *own* store: the agent
writes and edits it through a runtime tool, and it is addressed by the agent it
belongs to plus the end-user partition it was written in, never bound by id.

Two columns carry the capability's safety story, and both look like ordinary
metadata until you know what turns on them:

`origin` records who wrote the row - `operator` (a person, through the
management API) or `agent` (a tool call mid-run). It is the trust tier: only
`operator` content is ever spliced into the instructions, because an
agent-authored row is untrusted input a later run must reach as a tool result,
never as a prompt it obeys. An operator editing an agent-authored row does NOT
launder its origin - promotion to trusted is a separate, deliberate act.

`end_user_scope_key` is the per-end-user partition. `NULL` is the `shared`
partition - one store per (organization, agent), read by every end-user the
agent serves. A non-null key (`user:<id>` or `chan:<id>`) is a private store for
one end-user - the personal tier. The key is derived server-side from the
request identity and never chosen by the model, so a run can only ever read the
partition it was admitted to. Because a `NULL` key means "the one shared store"
rather than "a missing value", the unique constraint is `NULLS NOT DISTINCT`:
two shared files with one name are the collision the model has to be stopped
from creating, and plain SQL `NULL` would let them both exist.
"""

import uuid
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MemoryOrigin(StrEnum):
    """Who wrote a memory row, and therefore whether it may be trusted as prompt."""

    OPERATOR = "operator"
    """A person, through the management API. Trusted - injectable into instructions."""

    AGENT = "agent"
    """A tool call mid-run. Untrusted - reachable only as a tool result, never injected."""


class AgentMemoryFile(Base, TimestampMixin):
    """One named memory file belonging to an agent, in one end-user partition."""

    __tablename__ = "agent_memory_files"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL is the shared partition; `user:<id>`/`chan:<id>` is one end-user's private
    # store. Derived server-side, never model-chosen.
    end_user_scope_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A rendering hint - presentation, not behaviour, so it is not constrained.
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="md")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="note")
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MemoryOrigin.AGENT.value
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "agent_id",
            "end_user_scope_key",
            "name",
            name="uq_agent_memory_file_scope_name",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("origin IN ('operator', 'agent')", name="ck_agent_memory_file_origin"),
    )

    def __repr__(self) -> str:
        return f"<AgentMemoryFile(agent={self.agent_id}, name={self.name}, origin={self.origin})>"


class AgentMemoryFact(Base, TimestampMixin):
    """One fact an agent chose to remember, for semantic recall in a later run.

    The `facts` half of the capability. It has no name, but - like a file - it
    carries an `origin`, because both halves of "a fact is never trusted as a
    prompt" stopped being true: an operator can seed a fact through the management
    API, and the standing memory brief injects remembered facts into the agent's
    instructions. So `origin` is the same trust tier a file's is, and it governs
    the brief: only content safe to inject reaches it - a person's own facts (self
    scoped) and operator-authored shared ones - while an agent-authored *shared*
    fact is reachable only through the runtime `recall` tool, never spliced into a
    prompt every end-user of the agent would then obey.

    The vector is deliberately **not** a column here. There is no pgvector
    SQLAlchemy type in this project, and the width is the deployment's frozen
    embedding dimension, so the `embedding vector(N)` column and its HNSW index
    are created in the migration as raw SQL and written and searched through raw
    SQL in the repository; `alembic/env.py` excludes that one column from
    autogenerate so the model omitting it does not read as drift. The scope
    columns below are ordinary and Alembic-managed, which is what gives an
    operator a table to list, read and clear facts from.
    """

    __tablename__ = "agent_memory_facts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    end_user_scope_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MemoryOrigin.AGENT.value
    )

    __table_args__ = (
        CheckConstraint("origin IN ('operator', 'agent')", name="ck_agent_memory_fact_origin"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentMemoryFact(agent={self.agent_id}, "
            f"scope={self.end_user_scope_key}, origin={self.origin})>"
        )
