"""A person's arrangement of their own dashboard, per organization.

The dashboard resolves an audience layout from the caller's permissions; this
row is the third layer over that — a stored preference that reorders, hides,
resizes or adds cards. It is deliberately **not** a column on `users`: the
same person is a steward in one organization and a member in another, and a
single layout across both is wrong in one of them. So the layout is keyed on
`(user_id, organization_id)` and cascades from either side — a removed
membership leaves no orphan preference behind.

The arrangement itself is a JSONB array of entries, each one of two kinds: a
widget placement `{"kind": "widget", "widget", "span", "rows"?}` (`rows` is the
card's height, absent on arrangements saved before heights existed) or a section
divider `{"kind": "section", "label", "accent", "collapsed"?}` that groups,
colours and optionally folds the cards beneath it. An entry with no `kind` is
read as a widget, so arrangements saved before dividers existed still
round-trip. It is validated against the
widget registry **on write** (see `app/schemas/dashboard_layout.py`); nothing
about it is trusted on read, because a widget id valid when it was saved may
have been retired since, and the frontend drops what its registry no longer
knows rather than the backend refusing to return the row.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base, TimestampMixin


class DashboardLayout(Base, TimestampMixin):
    """One person's saved dashboard arrangement in one organization."""

    __tablename__ = "dashboard_layouts"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_dashboard_layout_user_org"),
    )

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
    # An ordered list of widget placements (`{"kind": "widget", "widget",
    # "span", "rows"?}`) and section dividers (`{"kind": "section", "label",
    # "accent", "collapsed"?}`). An empty list is a valid, deliberate state — a
    # person who has hidden every card — and is not the same as no row at all,
    # which means "use the audience default".
    entries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    def __repr__(self) -> str:
        return (
            f"<DashboardLayout(user={self.user_id}, org={self.organization_id}, "
            f"widgets={len(self.entries)})>"
        )
