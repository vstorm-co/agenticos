"""Per-organization Shop live-agent settings (D3 B53)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ShopLiveAgentOrgSettings(Base, TimestampMixin):
    __tablename__ = "shop_live_agent_org_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    live_agent_round_robin_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    live_agent_auto_assign_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    live_agent_idle_release_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
