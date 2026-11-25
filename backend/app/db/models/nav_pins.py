"""The sidebar items a person pinned, per organization.

Keyed on `(user_id, organization_id)` and cascading from either side, for the
same reason as `dashboard_layouts`: one person pins different things in
different organizations, and a removed membership must leave no preference
behind. `item_ids` is an ordered JSONB array of stable navigation item ids.
The ids belong to the frontend's navigation registry, so nothing here trusts
them on read; the client ignores any id it no longer knows or that the person
may not see. A pin never grants access.
"""

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base, TimestampMixin


class NavPins(Base, TimestampMixin):
    """One person's ordered pinned navigation items in one organization."""

    __tablename__ = "nav_pins"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_nav_pins_user_org"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    def __repr__(self) -> str:
        return f"<NavPins(user={self.user_id}, org={self.organization_id}, n={len(self.item_ids)})>"
