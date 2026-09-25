"""DirectoryGroupMapping - what a directory group means inside one organization.

A company's directory already says who is in Finance and who administers the
platform. A mapping lets an organization take that answer instead of keeping a
second copy by hand: whoever signs in carrying `external_group` becomes a member
with `role`, and joins `group_id` when one is named (#1773).

`external_group` is what the identity provider reports - an LDAP group DN, an
OIDC `groups` claim value such as an Entra object id or a Keycloak group path.
It is stored case-folded, because every one of those is compared
case-insensitively by the systems that issue them, and the unique constraint
has to mean the same thing the match does.
"""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DirectoryGroupMapping(Base, TimestampMixin):
    """One directory group, mapped to a role and optionally a group in one organization."""

    __tablename__ = "directory_group_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_group: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "external_group", name="uq_directory_mapping_org_group"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DirectoryGroupMapping(org={self.organization_id}, "
            f"external={self.external_group}, role={self.role})>"
        )
