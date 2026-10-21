"""A worker process that is, or recently was, running background jobs."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BackgroundWorker(Base):
    """One worker process, by the id it claims jobs under (#2219).

    For the panel and the health probe: who is alive, serving which pools,
    and when each last said so. Nothing about a job depends on this row - a
    job held by a worker that vanished is recovered by its lease running out,
    whatever the worker's id was - so a worker that comes back as a new
    container under a new id leaves no job behind.
    """

    __tablename__ = "background_workers"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    pools: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<BackgroundWorker(id={self.id}, pools={self.pools})>"
