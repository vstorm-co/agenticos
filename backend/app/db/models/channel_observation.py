"""A bounded pending window per binding and native conversation."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChannelObservation(Base):
    __tablename__ = "channel_observations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    exposure_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_exposures.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    admission_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform_chat_id: Mapped[str] = mapped_column(String(512), nullable=False)
    messages: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    mentioned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("exposure_id", "platform_chat_id", name="uq_channel_observation_thread"),
        Index("ix_channel_observations_due", "next_check_at"),
    )

    def __repr__(self) -> str:
        return f"ChannelObservation(id={self.id}, revision={self.revision})"


class ChannelObservationReceipt(Base):
    __tablename__ = "channel_observation_receipts"

    exposure_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_exposures.id", ondelete="CASCADE"),
        primary_key=True,
    )
    message_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_channel_observation_receipts_expiry", "expires_at"),)

    def __repr__(self) -> str:
        return f"ChannelObservationReceipt(exposure_id={self.exposure_id})"
