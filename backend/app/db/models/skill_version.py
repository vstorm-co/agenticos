"""Skill versions, the forks they belong to, and the files they snapshot.

A skill used to be one live row: an edit reached every agent at once, and nothing
recorded what it said before. Every saved change now makes a `SkillVersion`, which
is never updated afterwards, so an agent can stay on the text it was checked with
and a person can bring an earlier text back.

**Lines.** A version belongs to the skill's main line (`fork_id` is null) or to one
`SkillFork`, and is numbered within its line. A fork starts from a main version and
never from another fork's, so the history is the main line with branches one level
deep. A fork with no versions of its own serves the main version it started from.

**The `skills` row mirrors main, latest.** Its `content`, `description`, `version`
and files are what the newest main version says, kept in step by the one service
that writes versions - so every reader that predates versions still reads the text
an agent on main gets.

**Files are stored once.** A version's `resources` is a manifest of names, sizes
and content hashes; the bodies live in `SkillFile`, one row per distinct body per
skill. Editing the instructions of a skill with eighty reference files would
otherwise copy all eighty into every version.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TypedDict

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SkillVersionSource(StrEnum):
    """What made a version - the History tab says it beside each one."""

    BACKFILL = "backfill"
    """The text a skill had when versions began; earlier texts were never recorded."""
    CREATED = "created"
    EDIT = "edit"
    RESOURCES = "resources"
    """A file was added, changed or removed."""
    LIBRARY = "library"
    """Installed from, or brought up to, the bundled library or the gallery."""
    WORKSPACE = "workspace"
    """An agent's change to the files in its workspace, accepted by a person."""
    IMPROVE = "improve"
    """The assistant's proposal, accepted by a person."""
    RESTORE = "restore"
    CATCH_UP = "catch_up"
    """A fork took main's changes in, and is based on main's newest version since."""
    FROM_FORK = "from_fork"
    """Main took a fork's changes in."""


class ManifestEntry(TypedDict):
    """One file as a version records it; the body is the `SkillFile` with this hash."""

    sha256: str
    description: str | None
    size_bytes: int


def _values(enum: type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum)


class SkillFork(Base, TimestampMixin):
    """A named line of a skill, started from one of its main versions."""

    __tablename__ = "skill_forks"

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
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_versions.id", ondelete="CASCADE", use_alter=True),
        nullable=False,
        index=True,
    )
    """The main version the fork is based on now: the one it started from, or the one
    it last caught up with. Never a fork's own version: the service refuses a fork of
    a fork, so the tree stays one level deep."""

    started_from_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_versions.id", ondelete="CASCADE", use_alter=True),
        nullable=False,
        index=True,
    )
    """The main version the fork was started from, which catching up never moves."""

    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    """The fork's newest own version, or null while it has none and serves its base."""

    created_for_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_skill_forks_tenant"),
        # Archived names stay taken: an agent's history says which fork it ran on,
        # and a second fork of the same name would make that ambiguous.
        UniqueConstraint("skill_id", "name", name="uq_skill_forks_name"),
    )

    def __repr__(self) -> str:
        return f"<SkillFork(id={self.id}, skill={self.skill_id}, name={self.name})>"


class SkillVersion(Base):
    """One saved text of a skill, on its main line or on a fork. Never updated."""

    __tablename__ = "skill_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    fork_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    resources: Mapped[dict[str, ManifestEntry]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    restored_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The other line's version this one took in: main's for a fork catching up, the
    # fork's for its changes moved to main.
    merged_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skill_proposals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    library_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

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
            use_alter=True,
        ),
        UniqueConstraint("id", "organization_id", name="uq_skill_versions_tenant"),
        # Numbered per line: main's v3 and a fork's v3 are different versions.
        Index(
            "uq_skill_versions_main_number",
            "skill_id",
            "number",
            unique=True,
            postgresql_where=text("fork_id IS NULL"),
        ),
        Index(
            "uq_skill_versions_fork_number",
            "fork_id",
            "number",
            unique=True,
            postgresql_where=text("fork_id IS NOT NULL"),
        ),
        Index("ix_skill_versions_skill", "organization_id", "skill_id", "created_at"),
        CheckConstraint("number >= 1", name="ck_skill_version_number"),
        CheckConstraint(
            f"source IN ({_values(SkillVersionSource)})", name="ck_skill_version_source"
        ),
    )

    def __repr__(self) -> str:
        line = "main" if self.fork_id is None else f"fork={self.fork_id}"
        return f"<SkillVersion(skill={self.skill_id}, {line}, v{self.number})>"


class SkillFile(Base):
    """One distinct file body of a skill, shared by every version whose manifest names it."""

    __tablename__ = "skill_files"

    skill_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            ondelete="CASCADE",
        ),
    )

    def __repr__(self) -> str:
        return f"<SkillFile(skill={self.skill_id}, sha256={self.sha256[:12]})>"
