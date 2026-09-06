"""An agent's own notes - written by the agent, and by nothing else.

Unlike a context file (a human-authored library row bound to many agents and
read-only to the model), a memory note is the agent's own: it writes and edits one
through a runtime tool, and it is addressed by the agent it belongs to plus the
owner it was written for, never bound by id.

Nobody else writes here, and that is the line between the two features rather than
a limitation. `context` is what a person authors; memory is what the agent
learned. An operator-authored memory store existed and went, along with the trust
tier it needed, because it was a second mechanism for the first feature's job
(#1470).

`owner_key` says whose the note is. `person:<user_id>` (or
`person:chan:<identity_id>` for a chat account with no app user) is one human
being; `room:<platform>:<chat_id>` is one group chat. It is `NOT NULL`: every note
belongs to somebody, so the uniqueness of a name within a store is plain SQL
uniqueness rather than the `NULLS NOT DISTINCT` an org store used to require.

The prefixes are built and read in `app.core.memory_keys` - a leaf module, because
importing one model from here runs the whole `app.db.models` package and reaches
the capability registry through it.

Who may *read* a note back is a different question, belonging to the run rather
than the row, and it lives in :class:`app.agents.audience.RunAudience`.
Keeping them apart is the whole design: one column answering both is what let a
note written in a private chat be read back aloud in a group channel, because
"this person's store" and "somewhere only this person is listening" had been
collapsed into a single value (#788).
"""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AgentMemoryFile(Base, TimestampMixin):
    """One named note belonging to an agent, in one owner's store."""

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
    # `person:…` or `room:…` - see the module docstring. Derived server-side from
    # who is listening to the run, never model-chosen.
    owner_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A rendering hint - presentation, not behaviour, so it is not constrained.
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="md")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="note")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "agent_id",
            "owner_key",
            "name",
            name="uq_agent_memory_file_owner_name",
        ),
    )

    def __repr__(self) -> str:
        return f"<AgentMemoryFile(agent={self.agent_id}, owner={self.owner_key}, name={self.name})>"
