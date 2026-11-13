"""Which skills a run used - one row per run, agent and skill.

A skill reaches a run as a deferred capability. The model sees its name and
description and opens it with `read_skill`; it reads the skill's files with
`read_skill_resource`, or, where the run has a workspace, under
`/workspace/skills/<name>/` with the sandbox's own tools. Each of those is
counted here, by the skill's id rather than its name: a deleted skill's name may
be taken again by another one.

A delegate's use is a row of the run that delegated, under the delegate's
agent: the answer a person rated is that run's, and the skill was the
delegate's.

A row names ids only, never what was asked or said, and lives exactly as long as
its run: retention removes it with the run.

`agent_runs.skill_uses_recorded` says whether a run was recorded at all. A run
from before this table, or one whose usage could not be written, has no rows and
reads false - "unknown", which is not the same as "used nothing".
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunSkillUse(Base):
    """One skill one run used: how, and at which version."""

    __tablename__ = "run_skill_uses"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The agent that used the skill, which for a delegate is the delegate.
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The stored version the run was served. Null where none is known: a run
    # recorded before skills had versions, or a candidate body (`projected`).
    skill_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The body was a proposed one an eval served in place of the stored skill.
    projected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    loaded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    resource_reads: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # A weaker sign than the two above: a path a shell assembled is missed, and one
    # merely mentioned is counted.
    workspace_reads: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # The run's start, so a window over one skill is one index range.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "agent_id", "skill_id", name="uq_run_skill_uses_run_agent_skill"
        ),
        # Led by the referenced id, so deleting a skill or an agent finds its rows.
        Index("ix_run_skill_uses_skill", "skill_id", "created_at"),
        Index("ix_run_skill_uses_agent", "agent_id"),
        Index("ix_run_skill_uses_organization", "organization_id"),
    )

    def __repr__(self) -> str:
        return f"<RunSkillUse(run={self.run_id}, skill={self.skill_id}, loaded={self.loaded})>"
