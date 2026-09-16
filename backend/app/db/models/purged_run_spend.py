"""What a purged run cost, after the run itself is gone.

A retention policy that keeps the rows is not a retention policy, so the sweep
hard-deletes `agent_runs` - and the monthly bill is a sum over exactly those
rows. Without this table, an organization on a thirty-day run retention would
watch its month-to-date spend fall to zero on the thirty-first, and a budget cap
metered on that figure would stop enforcing (#1420).

One row per organization per calendar month, carrying the total the deleted runs
had spent and how many there were. It holds no content: not which agent, not
which model, not who asked - a number and a count, which is the whole of what the
cap and the invoice need. `app/services/spend.py` adds it to the live sum, and
that is the only place the two meet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PurgedRunSpend(Base, TimestampMixin):
    """The spend of runs a retention sweep removed, by month."""

    __tablename__ = "purged_run_spend"
    __table_args__ = (
        UniqueConstraint("organization_id", "period_start", name="purged_run_spend_period_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Midnight on the first of the month the purged runs started in, UTC.

    The month, not the day: a cap is metered on a calendar month and a report
    covers one, so a finer grain would be rows nobody queries at a resolution
    nobody asks for - and a coarser one could not answer either question.
    """

    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    """To the same scale as `agent_runs.cost_usd`, because it is summed with it."""

    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """How many runs went into the figure. For the sweep's own audit entry."""

    def __repr__(self) -> str:
        return (
            f"<PurgedRunSpend(org={self.organization_id}, "
            f"period={self.period_start:%Y-%m}, cost={self.cost_usd})>"
        )
