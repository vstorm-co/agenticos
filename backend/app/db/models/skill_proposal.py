"""A change an agent made to a skill, waiting for somebody to accept it.

An agent with a workspace and skills gets those skills as files - the body as
`SKILL.md`, each resource beside it - which is what makes a skill's script
runnable at all: it is on disk next to the shell that can run it. Writable files
follow from that, and so does the question this table answers.

**Why the change is not simply applied.** A skill is organizational know-how that
every agent bound to it reads on every run. An agent that could edit one directly
could rewrite the instructions another agent follows, in a conversation nobody is
reviewing, and the next reader would have no way to tell a considered improvement
from a hallucinated one. So the write lands here, a person accepts or discards it,
and `skills.version` moves only when they do.

**Why the whole body rather than a diff.** The proposal has to be applicable weeks
later, after the skill itself may have moved. A stored diff would either fail to
apply or apply somewhere it was never meant to; a stored body makes the conflict
visible - the reviewer is comparing two complete versions - which is the only form
in which that decision can be made honestly.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ProposalStatus(StrEnum):
    """Where a proposal is. Terminal once decided - see `SkillProposal.status`."""

    PENDING = "pending"
    APPLIED = "applied"
    DISCARDED = "discarded"


class SkillProposal(Base, TimestampMixin):
    """One agent-authored skill change, and who decided about it."""

    __tablename__ = "skill_proposals"
    __table_args__ = (
        # A reviewer's only query: what is waiting, in this organization, newest
        # first. Composite because filtering on status alone would scan every
        # decided proposal the deployment has ever recorded.
        Index("ix_skill_proposals_pending", "organization_id", "status"),
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

    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """Which skill this edits, or `None` for one the agent wrote from nothing.

    `CASCADE`: a proposal against a deleted skill has nothing left to apply to,
    and keeping it would offer a reviewer a change to a skill that is gone.
    """

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """Which agent wrote it. `SET NULL` because the proposal is a record of what
    happened, and deleting the agent does not unmake it."""

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    """Where it was written, so a reviewer can read the exchange that produced it.

    That context is most of what makes the decision possible: "rewrite the refund
    policy" means something different asked by a support lead than inferred by an
    agent from one customer's complaint.
    """

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    resources: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """The resource files as `{name: content}`.

    JSONB rather than rows in `skill_resources`: these are not resources yet.
    Writing them there would make a proposal indistinguishable from an applied
    change for every reader that joins on `skill_id`.
    """

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ProposalStatus.PENDING.value, index=True
    )
    """`pending`, `applied` or `discarded`, and terminal once it is not pending.

    The same rule approvals follow, for the same reason: a second decision on a
    decided change is either a duplicate application or one reviewer silently
    overruling another.
    """

    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<SkillProposal(name={self.name}, status={self.status})>"
