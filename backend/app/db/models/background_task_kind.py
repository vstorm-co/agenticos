"""What the deployment knows about one kind of background job: whether it is paused, and why."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BackgroundTaskKind(Base, TimestampMixin):
    """The circuit breaker for one kind of job (#2219).

    A worker death - a lease that ran out, a child process the kernel or the
    memory watchdog killed - adds one to `consecutive_deaths`; any job of the
    kind that ends without killing anything puts it back to zero. At the
    threshold the kind is paused: workers stop claiming it, the deployment's
    owners are told in the app and by email, and it stays paused until one of
    them resumes it. Each job's own `max_attempts` already stops one bad job
    from looping; this stops a kind from killing workers job after job.

    A row exists only for a kind that has died or been paused at least once.
    """

    __tablename__ = "background_task_kinds"

    kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    consecutive_deaths: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_lost: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    """Jobs that finished after another worker had taken them over: possible duplicates."""
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<BackgroundTaskKind(kind={self.kind}, deaths={self.consecutive_deaths}, "
            f"paused={self.paused_at is not None})>"
        )
