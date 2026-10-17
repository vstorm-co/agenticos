"""Round-robin cursor for Shop live-agent CS assignment (D3 B53)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ShopLiveAgentRoundRobinState(Base):
    __tablename__ = "shop_live_agent_round_robin_state"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    pool_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
