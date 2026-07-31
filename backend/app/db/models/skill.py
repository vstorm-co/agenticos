"""Skills - reusable instructions an agent loads on demand.

A skill is a piece of an organization's know-how written once and attached to
many agents: how refunds are handled, what the house style is, which checks a
report must pass. The agent sees only names and one-line descriptions until it
decides one is relevant, then loads the body - so twenty skills cost almost
nothing in context, and the twenty-first does not push the conversation out.

Skills live in the database rather than on disk because they are *content*, not
code: a support lead should be able to fix the refund policy without a deploy,
and two organizations on one deployment must not see each other's.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class Skill(Base, TimestampMixin):
    """One unit of organizational know-how."""

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )

    # The handle the model uses to load it. Unique per org so an agent bound to
    # two skills cannot end up with an ambiguous reference.
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # The one line the model reads before deciding to load the body - this is
    # what makes progressive disclosure work, so it earns its own column.
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A grouping label for people ("marketing", "devops"), not for the model -
    # the picker filters by it. Nullable: a skill without one is uncategorized,
    # which is a fine thing for a skill to be.
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    resources: Mapped[list["SkillResource"]] = relationship(
        "SkillResource",
        back_populates="skill",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_skill_org_name"),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_skill_visibility"),
    )

    def __repr__(self) -> str:
        return f"<Skill(org={self.organization_id}, name={self.name})>"


class SkillResource(Base, TimestampMixin):
    """A file a skill can hand the model when it needs the detail.

    Stored inline rather than in object storage: these are templates, checklists
    and examples measured in kilobytes, and keeping them in the row means a
    skill is one thing to back up, export and delete rather than two.
    """

    __tablename__ = "skill_resources"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    skill: Mapped[Skill] = relationship("Skill", back_populates="resources")

    @property
    def size_bytes(self) -> int:
        """What a listing reports instead of the body - see `SkillResourceSummary`."""
        return len(self.content.encode("utf-8"))

    __table_args__ = (UniqueConstraint("skill_id", "name", name="uq_skill_resource_name"),)

    def __repr__(self) -> str:
        return f"<SkillResource({self.name})>"
