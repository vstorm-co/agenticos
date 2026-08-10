"""A named dashboard arrangement a person saves and switches back to.

Where `dashboard_layouts` holds the one arrangement the dashboard currently
renders, a preset is a snapshot kept on the shelf: "Monday review", "Incident
watch". Applying one copies its entries into the active arrangement rather
than referencing the preset row, so editing after applying diverges from the
preset — the same contract as "save as" everywhere else.

Presets share the layout's tenant boundary: keyed on
`(user_id, organization_id)` plus a per-person, per-organization unique name,
cascading from both sides so a removed membership leaves nothing behind. The
entries carry the same `{"widget", "span", "rows"?}` placements, validated on
write and returned untrusted on read (see `app/schemas/dashboard_layout.py`).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base, TimestampMixin


class DashboardPreset(Base, TimestampMixin):
    """One named dashboard arrangement one person keeps in one organization."""

    __tablename__ = "dashboard_presets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id", "name", name="uq_dashboard_preset_user_org_name"
        ),
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
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    entries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    def __repr__(self) -> str:
        return (
            f"<DashboardPreset(user={self.user_id}, org={self.organization_id}, "
            f"name={self.name!r}, widgets={len(self.entries)})>"
        )
