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


class EditRatioBucket(BaseSchema):
    """How many approved requests changed the proposal by a share within one range."""

    upto: float = Field(
        description="The bucket's upper bound: 0.0, 0.1, 0.25, 0.5 or 1.0. It holds ratios "
        "above the previous bound and up to this one; the 0.0 bucket holds exactly 0"
    )
    count: int


class ApprovalOutcomes(BaseSchema):
    """What the approval requests of real runs came to, over a window.

    Every figure counts requests by the day they were asked. The rates and
    quantiles are facts about what people did, not a verdict on the workflow.
    """

    requests: int = Field(description="Every request asked in the window")
    pending: int = Field(description="Still waiting for a decision")
    approved_unchanged: int = Field(
        description="Approved with the proposal as it was, including steps that cannot be edited"
    )
    approved_edited: int = Field(description="Approved after the approver changed the proposal")
    rejected: int = Field(description="Turned down by an approver")
    expired: int = Field(description="Ran out of time with no decision; not counted as decided")
    cancelled: int = Field(description="Closed because the run was cancelled; not decided")
    acceptance_rate: float | None = Field(
        default=None,
        description="Approved (unchanged or edited) out of the decided requests, "
        "approved plus rejected; null when none was decided",
    )
    unchanged_rate: float | None = Field(
        default=None,
        description="Approved unchanged out of the decided requests; null when none was decided",
    )
    decide_p50_seconds: float | None = Field(
        default=None,
        description="Median time from the request to the decision, over approved and "
        "rejected requests; null when none was decided",
    )
    decide_p95_seconds: float | None = Field(
        default=None,
        description="The 95th percentile of the same time, over approved and rejected "
        "requests; null when none was decided",
    )
    edit_ratio_median: float | None = Field(
        default=None,
        description="Median share of the proposal an approver changed, over the edited "
        "requests that were measured: how much an edit changes. Null when none was",
    )
    edit_ratios: list[EditRatioBucket] = Field(
        description="Always the five buckets, zero-filled, over every request with a measured "
        "edit ratio. Requests decided before it was measured are in none of them"
    )


class WorkflowApprovalDay(BaseSchema):
    """One UTC day's requests, by how they ended."""

    day: date
    approved_unchanged: int = 0
    approved_edited: int = 0
    rejected: int = 0
    expired: int = 0


class WorkflowApprovalStep(ApprovalOutcomes):
    """One approval step's outcomes."""

    node_instance_id: UUID
    label: str | None = Field(
        default=None, description="The step's name in the live version, or null"
    )
    definition_id: str | None = Field(
        default=None, description="The step's type, or null for a step no longer in it"
    )


class WorkflowApprovalStats(ApprovalOutcomes):
    """A workflow's approval outcomes over the same window as its run figures."""

    by_day: list[WorkflowApprovalDay]
    steps: list[WorkflowApprovalStep] = Field(description="Each approval step, most requests first")


class WorkflowApprovalsSummaryRow(ApprovalOutcomes):
    """One workflow's approval outcomes over the window, for the organization-wide summary."""

    id: UUID
    name: str


class WorkflowApprovalsSummary(ApprovalOutcomes):
    """The approval outcomes of every workflow the caller may see, over a window of days."""

    workflows: list[WorkflowApprovalsSummaryRow] = Field(
        description="The workflows with the most requests, most first, at most five"
    )


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
    approvals: WorkflowApprovalStats


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
