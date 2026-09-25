"""Group and GroupMember - named sets of an organization's members.

A group is something a resource can be shared with: one grant reaches every
member of it, now and later, which is what sharing an agent with "Finance"
rather than with eleven addresses means. It carries no role. What a member may
do in the organization is still their membership's role; a group only widens
what they reach, through the grants made to it (#1773).

Membership has a source because two writers maintain it. An administrator adds
and removes people by hand; the directory sync adds and removes the people a
directory group mapping names. Each writer touches only its own rows, so a
directory sign-in never undoes an administrator's decision and an administrator
can see which memberships the next sign-in will rewrite.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin
from app.db.models.organization import MembershipSource, MembershipSourceLiteral


class Group(Base, TimestampMixin):
    """A named set of members inside one organization."""

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_group_org_name"),)

    def __repr__(self) -> str:
        return f"<Group(id={self.id}, org={self.organization_id}, name={self.name})>"


class GroupMember(Base):
    """One member's place in one group, and who put them there."""

    __tablename__ = "group_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[MembershipSourceLiteral] = mapped_column(
        String(16),
        nullable=False,
        default=MembershipSource.MANUAL.value,
        server_default=MembershipSource.MANUAL.value,
    )
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
        CheckConstraint("source IN ('manual', 'directory')", name="ck_group_member_source"),
    )

    def __repr__(self) -> str:
        return f"<GroupMember(group={self.group_id}, user={self.user_id}, source={self.source})>"
