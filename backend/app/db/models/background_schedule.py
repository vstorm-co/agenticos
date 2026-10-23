"""A recurring job the deployment runs on its own: a sweep, a report, a check."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BackgroundSchedule(Base, TimestampMixin):
    """When a schedule next fires, and what it does when it is late or still running (#2219).

    The schedules themselves are declared in code (`app/worker/schedules.py`);
    a worker writes them here when it starts, keeping `next_run_at`, so a
    restart neither fires everything at once nor forgets where it was. Any
    worker may fire a due schedule - the row is claimed `FOR UPDATE SKIP
    LOCKED` - so there is no single scheduler process to lose.

    `misfire` is what an occurrence later than `grace_seconds` does: `latest`
    fires once for the whole backlog, `skip` fires nothing and waits for the
    next one. `overlap` is what an occurrence does while the previous job is
    still queued or running: `skip` drops it, `queue` lets one wait behind it,
    `allow` runs it alongside.
    """

    __tablename__ = "background_schedules"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    overlap: Mapped[str] = mapped_column(String(8), nullable=False, server_default="skip")
    misfire: Mapped[str] = mapped_column(String(8), nullable=False, server_default="latest")
    grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint("interval_seconds > 0", name="interval_seconds"),
        CheckConstraint("overlap IN ('skip', 'queue', 'allow')", name="overlap"),
        CheckConstraint("misfire IN ('latest', 'skip')", name="misfire"),
        CheckConstraint("grace_seconds >= 0", name="grace_seconds"),
    )

    def __repr__(self) -> str:
        return f"<BackgroundSchedule(name={self.name}, next_run_at={self.next_run_at})>"
