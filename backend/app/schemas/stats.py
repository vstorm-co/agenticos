"""What the dashboard's usage endpoint answers with.

One composed response on purpose: the cards reading it ask about the same
window, so they share one query, one loading state and one failure instead of
eight half-loaded answers drifting apart. Every block is a slice of the same
set of runs, which is what keeps the numbers mutually consistent - the status
counts sum to `total_runs` because they are the same rows counted twice.
"""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.message_rating import RatingSummary


class DayCount(BaseSchema):
    """Runs started on one UTC day. Days with no runs are present with zero."""

    date: date
    runs: int


class SurfaceCount(BaseSchema):
    """Runs admitted by one surface, as recorded on the run.

    Historical wrinkle: widget runs recorded before the `embed` surface existed
    are stored as `web`, and early Mattermost runs as `api`. Old periods fold
    those into the surface they were recorded under - nothing is backfilled.
    """

    surface: str
    runs: int


class AgentCount(BaseSchema):
    """One agent's share of the window's runs."""

    agent_id: UUID
    name: str
    runs: int


class StatusCount(BaseSchema):
    """Runs that ended (or are parked) in one status."""

    status: str
    runs: int


class ModelCount(BaseSchema):
    """Runs executed by one model, as recorded on each run (`model_label`).

    Null means the run recorded no label - reported as its own row rather than
    folded into a model it may not have used.
    """

    model_label: str | None
    runs: int


class LatencyMs(BaseSchema):
    """Started-to-finished percentiles over the window's finished runs.

    Null when nothing in the window has an `ended_at` - an honest "no answer
    yet", distinct from a fast zero.
    """

    p50: int | None
    p95: int | None


class ActiveUsers(BaseSchema):
    """How many members ran anything, against how many there are.

    A count, deliberately not a table of names: adoption is answerable without
    shipping a surveillance table. Anonymous runs (an embedded widget's
    visitors) carry no user and are not counted as people.
    """

    active: int
    total_members: int


class ProviderCost(BaseSchema):
    """One provider's share of the window's model spend."""

    provider: str | None
    cost_usd: Decimal


class CostBlock(BaseSchema):
    """Model spend inside the window - the period half of the spend card.

    The calendar month-to-date figure deliberately lives on `GET /spend`
    instead: it reconciles against an invoice and must not move with a
    dashboard's period filter.
    """

    period_usd: Decimal
    previous_period_usd: Decimal
    by_provider: list[ProviderCost]


class ScopedRatingSummary(RatingSummary):
    """The rating summary's shape, bounded to a window and a scope.

    Same bones as the deployment-wide `GET /admin/ratings/summary` so the
    chart ports, plus the envelope saying which window and whose answers:
    `scope=org` is the organization's, `scope=own` the caller's own
    conversations. `ratings_by_day` stays sparse - days nobody rated are
    absent, as in the admin summary.
    """

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    scope: Literal["org", "own"]


class VersionUsageRow(BaseSchema):
    """One published version's share of the window - the compare card's row.

    `agent_version_id` survives on runs after the version is deleted (the
    foreign key SET-NULLs), so a null id with a null number is "a deleted
    version" - kept as a row rather than dropped, because the runs happened.
    Ratings count thumbs given in the window on messages this version
    produced; a version that predates message-level version stamping shows
    zero rather than borrowing a neighbour's numbers.
    """

    agent_version_id: UUID | None
    version: int | None
    runs: int
    completed_runs: int
    p95_ms: int | None
    avg_cost_usd: Decimal | None
    like_count: int
    rating_count: int


class UsageStats(BaseSchema):
    """The answer of `GET /stats/usage` - one envelope, sections per question.

    A composed request fills every `by_*` block plus `latency_ms` and `cost`;
    within it, `scope=org` carries `active_users` and `scope=own` carries
    `pending_approvals` instead - how many of the caller's runs are parked on
    somebody's decision, which answers "why is my agent stuck" for a member
    who cannot see the approval queue. A `group_by` request fills only its own
    section and leaves the composed blocks null: it is a different question
    about the same window, and computing eight answers nobody asked for would
    be waste dressed as consistency.
    """

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    scope: Literal["org", "own"]
    total_runs: int | None = None
    previous_total_runs: int | None = None
    by_day: list[DayCount] | None = None
    by_surface: list[SurfaceCount] | None = None
    by_agent: list[AgentCount] | None = None
    by_status: list[StatusCount] | None = None
    by_model: list[ModelCount] | None = None
    latency_ms: LatencyMs | None = None
    cost: CostBlock | None = None
    active_users: ActiveUsers | None = None
    pending_approvals: int | None = None
    agent_id: UUID | None = None
    by_version: list[VersionUsageRow] | None = None
