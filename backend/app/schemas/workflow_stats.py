"""What a workflow's real runs did over a window: the runs page's figures."""

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class WorkflowStatsDay(BaseSchema):
    """One UTC day of a workflow's real runs."""

    day: date
    succeeded: int = 0
    failed: int = 0
    other: int = Field(
        default=0, description="Every other run that day: cancelled, out of budget, under way"
    )
    cost_usd: float = 0.0


class WorkflowStatsStep(BaseSchema):
    """One step's share of the window's real runs."""

    node_instance_id: UUID
    label: str | None = Field(
        default=None, description="The step's name in the live version, or null"
    )
    definition_id: str | None = Field(
        default=None, description="The step's type, or null for a step no longer in it"
    )
    runs: int
    failed: int
    cost_usd: float
    avg_seconds: float | None = None


class WorkflowStats(BaseSchema):
    """How a workflow's real runs went over the last `days` days, and this month's spend."""

    days: int
    since: datetime
    runs: int
    succeeded: int
    failed: int
    ended: int = Field(description="The runs that ended, whichever way")
    success_rate: float | None = Field(
        default=None, description="Succeeded out of the runs that ended; null when none ended"
    )
    duration_p50_seconds: float | None = None
    duration_p95_seconds: float | None = None
    cost_usd: float
    cost_is_partial: bool
    month_cost_usd: float = Field(
        description="Every run's spend this calendar month in UTC, test runs included - "
        "what the monthly budget counts"
    )
    monthly_budget_usd: float | None = None
    by_day: list[WorkflowStatsDay]
    steps: list[WorkflowStatsStep]


class WorkflowSummaryRow(BaseSchema):
    """One workflow's real runs over the window, for the dashboard's card."""

    id: UUID
    name: str
    runs: int
    failed: int
    cost_usd: float


class WorkflowsSummary(BaseSchema):
    """The real runs of every workflow the caller may see, over a window of days."""

    runs: int
    succeeded: int
    failed: int
    cost_usd: float
    needs_you: int = Field(
        description="Runs under way now that wait for a person - an approval, or a step "
        "that needs attention"
    )
    workflows: list[WorkflowSummaryRow] = Field(
        description="The busiest of them, most runs first, at most five"
    )
