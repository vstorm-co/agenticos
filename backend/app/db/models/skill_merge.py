"""The three-way merge a session catching a fork up, or moving it to main, works on.

A session whose purpose is `catch_up` or `to_main` merges the version the fork is
based on, the fork's newest and main's newest once, when it starts, and keeps the
parts here. The model proposes a text for each conflict and a person may rewrite
any part before the check; the check then measures what the parts say together.

The three versions are recorded so accepting can refuse once either line moved on:
a merge of texts that are no longer the newest would write over a change nobody saw.
"""

import uuid
from typing import TypedDict

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.skill_version import ManifestEntry


class MergedPart(TypedDict):
    """One part of the merged text: what each side said there, and what the merge says.

    `result` is `None` for a conflict nobody has settled yet. `proposed` is the model's
    text for a conflict, kept beside a person's rewrite of it; `edited` says a person
    wrote `result`.
    """

    state: str
    base: str
    fork: str
    main: str
    result: str | None
    proposed: str | None
    edited: bool


class MergedFile(TypedDict):
    """One file of the merge, as each side's manifest lists it; `None` where it is absent.

    `take` names the side the merge keeps, `None` while a conflict waits for a person.
    """

    name: str
    state: str
    base: ManifestEntry | None
    fork: ManifestEntry | None
    main: ManifestEntry | None
    take: str | None


class SkillMerge(Base, TimestampMixin):
    """One session's merge of a fork with main."""

    __tablename__ = "skill_merges"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    fork_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    """The session's purpose: `catch_up` or `to_main`."""
    base_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    fork_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    main_version_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    description: Mapped[MergedPart] = mapped_column(JSONB, nullable=False)
    parts: Mapped[list[MergedPart]] = mapped_column(JSONB, nullable=False)
    files: Mapped[list[MergedFile]] = mapped_column(JSONB, nullable=False)
    conflicts: Mapped[int] = mapped_column(Integer, nullable=False)
    """How many texts both sides changed differently - the description and the parts.
    Files are not counted: the model never writes one, a person picks a side."""
    unresolved: Mapped[int] = mapped_column(Integer, nullable=False)
    """The texts and files still waiting for a side or a text; the check waits for none."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["fork_id", "organization_id"],
            ["skill_forks.id", "skill_forks.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "organization_id"],
            ["skill_improvement_runs.id", "skill_improvement_runs.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["base_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["fork_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["main_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", name="uq_skill_merges_run"),
        # Deleting a skill, fork or version cascades into these; unindexed, each scans the table.
        Index("ix_skill_merges_skill", "skill_id"),
        Index("ix_skill_merges_fork", "fork_id"),
        Index("ix_skill_merges_base_version", "base_version_id"),
        Index("ix_skill_merges_fork_version", "fork_version_id"),
        Index("ix_skill_merges_main_version", "main_version_id"),
        CheckConstraint("kind IN ('catch_up', 'to_main')", name="ck_skill_merge_kind"),
        CheckConstraint("unresolved >= 0 AND conflicts >= 0", name="ck_skill_merge_counts"),
    )

    def __repr__(self) -> str:
        return f"<SkillMerge(id={self.id}, run={self.run_id}, {self.kind})>"
