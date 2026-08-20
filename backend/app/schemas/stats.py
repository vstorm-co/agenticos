"""What the dashboard's usage endpoint answers with.

One composed response on purpose: the cards reading it ask about the same
window, so they share one query, one loading state and one failure instead of
eight half-loaded answers drifting apart. Every block is a slice of the same
set of runs, which is what keeps the numbers mutually consistent - the status
counts sum to `total_runs` because they are the same rows counted twice.

That set is **top-level runs only**: a delegated run's tokens are already
inside its parent's row, so counting both would bill one run twice, and a
delegated row copies its parent's `user_id` and `surface`, so counting both
would also invent a second person and a second arrival. `by_agent` is the one
block that departs from this and says why on
:func:`app.repositories.agent_run.runs_by_agent`; its bars can therefore
exceed `total_runs`, and nothing sums them.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.message_rating import RatingSummary


class DayCount(BaseSchema):
    """One UTC day's runs, how many completed, and what they cost.

    Days with no runs are present with zeroes, so a series is dense and a
    sparkline has one point per day rather than one point per day that
    happened to be busy.
    """

    date: date
    runs: int
    completed: int
    cost_usd: Decimal


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
    """The window's whole bill, and the two halves it is made of.

    `period_usd` is models **plus ingestion plus retrieval**, which is the same
    arithmetic `spend.organization_spend_since` measures a monthly cap on. It
    used to be models alone, so the dashboard's headline and the month-to-date
    line under it were two different definitions of cost sitting on one card with
    nothing saying so - on a deployment that indexes documents they simply
    disagreed.

    `model_usd`, `ingestion_usd` and `retrieval_usd` sum to it. They are separate
    fields rather than a computed split because they are answered by different
    tables and sources, and a reader deciding where the money went should not
    have to subtract. `retrieval_usd` is what a metered `POST /rag/search` spent
    on embeddings and reranking - kept apart from `ingestion_usd` so a search is
    not reported as indexing.

    `previous_period_usd` is the whole bill too, so the change against the last
    window compares like with like.

    The calendar month-to-date figure still lives on `GET /spend`: it
    reconciles against an invoice and must not move with a period filter.
    """

    period_usd: Decimal
    previous_period_usd: Decimal
    model_usd: Decimal
    ingestion_usd: Decimal
    retrieval_usd: Decimal
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


class PersonUsageRow(BaseSchema):
    """One person's share of the window - the who-is-using-it card's row.

    Runs with no user behind them are excluded rather than collected into an
    "unattributed" row: a channel message from somebody with no account, and a
    run whose user was deleted (the foreign key SET-NULLs), both land in that
    bucket, and neither is a person this card can name. That exclusion is also
    what keeps the card consistent with the `active_users` count it sits
    under, which counts distinct non-null users over the same rows.

    Ordered by `runs`, deliberately not by cost - the same rows sorted by
    spend read as a league table, and the question the card answers is
    adoption. Cost rides along as a column because the alternative is the
    reader cross-referencing it by hand.
    """

    user_id: UUID
    email: str
    full_name: str | None
    runs: int
    cost_usd: Decimal
    last_run_at: datetime


class HourCount(BaseSchema):
    """Runs started in one weekday-and-hour slot - the rhythm card's cell.

    `weekday` is Postgres' `dow`, so **0 is Sunday**; the client maps it onto
    whatever its locale calls the first day. Sparse: a slot nobody ever ran in
    is absent rather than present with a zero, because 168 rows of mostly
    nothing is a lot of envelope for an empty deployment.

    UTC, like every other bucket here. An organization spread across timezones
    reads its own rhythm shifted, which is the honest answer until a run
    records the zone it arrived from.
    """

    weekday: int
    hour: int
    runs: int


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
    by_user: list[PersonUsageRow] | None = None
    by_hour: list[HourCount] | None = None
