"""SyncLog model - tracks document synchronization history."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SyncLog(TimestampMixin, Base):
    __tablename__ = "sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sync_source_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sync_sources.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="full")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Who to notify about this sync's outcome (#1598) - set by
    # SyncSourceService.trigger_sync from the caller who dispatched it. Null on
    # a run the scheduler started (check_scheduled_syncs_flow): nobody
    # personally asked for it, so its notification falls back to the
    # organization's admins rather than resolving to nobody. SET NULL: deleting
    # the triggering user must not delete the sync's history.
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
