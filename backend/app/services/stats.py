"""Usage aggregates for the dashboard - one window, every slice at once.

Before this, nothing org-scoped aggregated: `/runs` pages through rows with
`limit <= 100`, `/spend` answers only cost, and `/admin/stats` is point-in-time
counts for the deployment's admin. Any "how much / how often" number computed
client-side was analytics over the most recent hundred rows, silently.

The scope decision lives here rather than on the route. `scope=own` must be
reachable by a plain member - their own rows are theirs to see at any role -
so a route-level `require(RUNS_VIEW)` would refuse half the endpoint's
callers before the parameter was ever read. The route therefore carries no
gate, and this service is registered among the route sweep's resource-aware
services: the same principle as the sharing rows (the layer that can see the
deciding fact decides), where the deciding fact is the `scope` parameter
rather than a grant on a row.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.permissions import Perm
from app.repositories import (
    agent_run_repo,
    group_repo,
    ingestion_spend_repo,
    member_repo,
    message_rating_repo,
)
from app.repositories.agent_run import RunFilter
from app.schemas.stats import (
    ActiveUsers,
    AgentCount,
    CostBlock,
    DayCount,
    HourCount,
    LatencyMs,
    ModelCount,
    PersonUsageRow,
    ProviderCost,
    ScopedRatingSummary,
    StatusCount,
    SurfaceCount,
    TimeBucket,
    Timeline,
    UsageStats,
    VersionUsageRow,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext

UsageScope = Literal["org", "own"]

_DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Window:
    """An inclusive date range and its half-open timestamp form, both UTC."""

    from_date: date
    to_date: date
    start: datetime
    end: datetime

    @property
    def previous(self) -> tuple[datetime, datetime]:
        """The same-length window ending where this one starts."""
        return self.start - (self.end - self.start), self.start


def resolve_window(
    from_date: date | None, to_date: date | None, *, today: date | None = None
) -> Window:
    """Turn inclusive ISO dates into a half-open UTC window.

    Inclusive `to` becomes `< to + 1 day` - the only reading under which a run
    started at 23:59:59 of the last day counts. Defaults to the last 30 days
    ending today; `today` is injectable so the arithmetic is testable.

    Raises:
        ValidationError: When `from` is after `to`.
    """
    anchor = today or datetime.now(UTC).date()
    to_actual = to_date or anchor
    from_actual = from_date or (to_actual - timedelta(days=_DEFAULT_WINDOW_DAYS - 1))
    if from_actual > to_actual:
        raise ValidationError(
            message="from is after to",
            details={"from": str(from_actual), "to": str(to_actual)},
        )
    return Window(
        from_date=from_actual,
        to_date=to_actual,
        start=datetime.combine(from_actual, time.min, tzinfo=UTC),
        end=datetime.combine(to_actual + timedelta(days=1), time.min, tzinfo=UTC),
    )


def _each_day(first: date, last: date) -> Iterator[date]:
    current = first
    while current <= last:
        yield current
        current += timedelta(days=1)


# The steps a timeline may take, finest first, and how many points it aims for.
_TIMELINE_STEPS = tuple(
    timedelta(seconds=seconds)
    for seconds in (60, 300, 900, 3600, 3 * 3600, 6 * 3600, 86400, 7 * 86400)
)
_TIMELINE_MAX_POINTS = 48
_TIMELINE_MIN_POINTS = 12


@dataclass(frozen=True)
class TimelinePlan:
    """The step a timeline is drawn at and the half-open range of bins it covers."""

    step: timedelta
    start: datetime
    end: datetime


def plan_timeline(window: Window, first_run: datetime | None, now: datetime) -> TimelinePlan:
    """Choose the step and range that draw the window's runs legibly.

    The span that matters runs from the window's first run to now, or to the
    window's end when that is earlier. The finest step that draws it in at
    most `_TIMELINE_MAX_POINTS` wins; the range then reaches back to show at
    least `_TIMELINE_MIN_POINTS`, inside the window. Bins are aligned to the
    window's start, so a day step lands on the same UTC days `by_day` does. A
    window nothing ran in is drawn by day, the whole window.
    """
    end = min(window.end, max(now, window.start))
    if first_run is None:
        return TimelinePlan(step=timedelta(days=1), start=window.start, end=window.end)
    span = end - first_run
    step = next(
        (each for each in _TIMELINE_STEPS if span / each <= _TIMELINE_MAX_POINTS),
        _TIMELINE_STEPS[-1],
    )
    # `end` is exclusive, so the last bin drawn is the one holding the instant
    # before it - a window ending on a step boundary gains no empty bin past it.
    last_bin = window.start + ((end - timedelta(microseconds=1) - window.start) // step) * step
    first_bin = window.start + ((first_run - window.start) // step) * step
    start = max(window.start, min(first_bin, last_bin - (_TIMELINE_MIN_POINTS - 1) * step))
    return TimelinePlan(step=step, start=start, end=last_bin + step)


class StatsService:
    """Usage aggregates, scoped to the organization or to the caller."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _scope_filter(self, ctx: AuthContext, scope: UsageScope) -> UUID | None:
        """None for the organization's rows, the caller's id for their own.

        `scope=org` reads everybody's runs and demands `runs:view`; `scope=own`
        demands only a subject. An app admin passes both, because their
        context holds every permission.

        Raises:
            AuthorizationError: `scope=org` without `runs:view`, or
                `scope=own` from a context with no subject.
        """
        if scope == "own":
            if ctx.user_id is None:
                raise AuthorizationError(message="scope=own needs a signed-in caller")
            return ctx.user_id
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Insufficient permissions",
                details={"required": [Perm.RUNS_VIEW.value], "scope": "org"},
            )
        return None

    async def _narrow(
        self,
        ctx: AuthContext,
        scope: UsageScope,
        *,
        agent_id: UUID | None,
        user_id: UUID | None,
        group_id: UUID | None = None,
    ) -> RunFilter:
        """The scope decision and the caller's own narrowing, as one filter.

        A dashboard card may be pinned to one agent or to one colleague while
        the page's filter stays where it is, so these are the same question as
        `scope` and answered in the same place. Narrowing to a colleague or to a
        group reads somebody else's rows, which is `scope=org` and therefore
        already behind `runs:view`; `scope=own` needs no such gate and cannot be
        pointed at anybody else.

        Raises:
            ValidationError: `scope=own` with a `user_id` or a `group_id` - it
                can only ever be the caller's own, and a request saying
                otherwise is a mistake worth answering rather than silently
                reinterpreting.
            NotFoundError: a `group_id` that is not one of this organization's
                groups.
        """
        if scope == "own" and (user_id is not None or group_id is not None):
            raise ValidationError(
                message="scope=own is already the caller; drop user_id and group_id",
                details={"scope": scope},
            )
        if group_id is not None:
            group = await group_repo.get(
                self.db, organization_id=ctx.organization_id, group_id=group_id
            )
            if group is None:
                raise NotFoundError(message="Group not found", details={"group_id": str(group_id)})
        return RunFilter(
            user_id=self._scope_filter(ctx, scope) or user_id,
            agent_id=agent_id,
            group_id=group_id,
        )

    async def usage(
        self,
        ctx: AuthContext,
        *,
        scope: UsageScope = "org",
        from_date: date | None = None,
        to_date: date | None = None,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> UsageStats:
        """The composed answer: totals, slices, latency and cost of one window."""
        where = await self._narrow(
            ctx, scope, agent_id=agent_id, user_id=user_id, group_id=group_id
        )
        window = resolve_window(from_date, to_date)
        prev_start, prev_end = window.previous
        org = ctx.organization_id

        # The window's scalars - count, cost, distinct users, latency percentiles -
        # share one WHERE, so the window is one query rather than four. The previous
        # window is only a count and a cost, so it takes the lighter aggregate and
        # does not sort durations for percentiles nobody reads.
        current = await agent_run_repo.window_aggregates(
            self.db, organization_id=org, start=window.start, end=window.end, where=where
        )
        previous_total, previous_model_usd = await agent_run_repo.window_totals(
            self.db, organization_id=org, start=prev_start, end=prev_end, where=where
        )
        total = current.total

        # Day, surface, status, model and provider grouped the same window's same
        # rows five ways; one GROUPING SETS scan reads them together (#949).
        breakdown = await agent_run_repo.window_breakdown(
            self.db, organization_id=org, start=window.start, end=window.end, where=where
        )
        day_rows = {row[0]: row for row in breakdown.by_day}
        by_day = [
            DayCount(
                date=day,
                runs=day_rows[day][1] if day in day_rows else 0,
                completed=day_rows[day][2] if day in day_rows else 0,
                cost_usd=day_rows[day][3] if day in day_rows else Decimal(0),
            )
            for day in _each_day(window.from_date, window.to_date)
        ]

        timeline = await self._timeline(org, window, where, current.first_started_at)

        by_surface = [
            SurfaceCount(surface=value or "", runs=runs) for value, runs in breakdown.by_surface
        ]
        by_status = [
            StatusCount(status=value or "", runs=runs) for value, runs in breakdown.by_status
        ]
        by_model = [
            ModelCount(model_label=value, provider=provider, runs=runs, tool_args_repaired=repaired)
            for value, provider, runs, repaired in breakdown.by_model
        ]
        by_agent = [
            AgentCount(agent_id=agent_id, name=name, runs=runs)
            for agent_id, name, runs in await agent_run_repo.runs_by_agent(
                self.db, organization_id=org, start=window.start, end=window.end, where=where
            )
        ]

        latency = LatencyMs(
            p50=round(current.p50_ms) if current.p50_ms is not None else None,
            p95=round(current.p95_ms) if current.p95_ms is not None else None,
        )

        # The whole bill, not the model half of it. `organization_spend_since`
        # has always measured a monthly cap on runs *plus* ingestion, so a
        # dashboard reporting runs alone put two definitions of cost on one
        # card - the headline and the month-to-date line under it - with
        # nothing saying which was which.
        #
        # Ingestion is the organization's, never one person's and never one
        # agent's: a document is indexed by a worker, and `ingestion_spend`
        # records neither. So any narrowed window - `scope=own`, a person, an
        # agent - reports model spend alone rather than billing a card for a
        # collection somebody else synced.
        model_usd = current.cost_usd
        ingestion_usd = Decimal(0)
        previous_ingestion_usd = Decimal(0)
        if where == RunFilter():
            ingestion_usd = await ingestion_spend_repo.sum_cost_window(
                self.db, organization_id=org, start=window.start, end=window.end
            )
            previous_ingestion_usd = await ingestion_spend_repo.sum_cost_window(
                self.db, organization_id=org, start=prev_start, end=prev_end
            )
        cost = CostBlock(
            period_usd=model_usd + ingestion_usd,
            previous_period_usd=previous_model_usd + previous_ingestion_usd,
            model_usd=model_usd,
            ingestion_usd=ingestion_usd,
            by_provider=[
                ProviderCost(provider=provider, cost_usd=cost_usd)
                for provider, cost_usd in breakdown.by_provider
            ],
        )

        # Keyed on the *person*, not on the filter as a whole: an agent-narrowed
        # window is still everybody's, and "how many people used this one" is
        # the adoption question worth asking of an agent.
        active_users = None
        pending_approvals = None
        if where.user_id is None:
            # A group's dashboard reaches the group, so its denominator is the
            # group's members rather than the whole organization's.
            active_users = ActiveUsers(
                active=current.distinct_users,
                total_members=(
                    await group_repo.count_members(self.db, where.group_id)
                    if where.group_id is not None
                    else await member_repo.count_for_org(self.db, org)
                ),
            )
        else:
            pending_approvals = await agent_run_repo.count_pending_approval_runs(
                self.db, organization_id=org, user_id=where.user_id
            )

        return UsageStats(
            from_date=window.from_date,
            to_date=window.to_date,
            scope=scope,
            total_runs=total,
            previous_total_runs=previous_total,
            by_day=by_day,
            timeline=timeline,
            by_surface=by_surface,
            by_agent=by_agent,
            by_status=by_status,
            by_model=by_model,
            latency_ms=latency,
            cost=cost,
            active_users=active_users,
            pending_approvals=pending_approvals,
        )

    async def _timeline(
        self, org: UUID, window: Window, where: RunFilter, first_run: datetime | None
    ) -> Timeline:
        """The window's runs at the step `plan_timeline` chooses, zero-filled."""
        plan = plan_timeline(window, first_run, datetime.now(UTC))
        rows = {
            bin_start: (runs, completed, cost)
            for bin_start, runs, completed, cost in await agent_run_repo.runs_by_bin(
                self.db,
                organization_id=org,
                start=plan.start,
                end=plan.end,
                step=plan.step,
                where=where,
            )
        }
        buckets: list[TimeBucket] = []
        bin_start = plan.start
        while bin_start < plan.end:
            runs, completed, cost = rows.get(bin_start, (0, 0, Decimal(0)))
            buckets.append(
                TimeBucket(start=bin_start, runs=runs, completed=completed, cost_usd=cost)
            )
            bin_start += plan.step
        return Timeline(step_seconds=int(plan.step.total_seconds()), buckets=buckets)

    async def usage_by_hour(
        self,
        ctx: AuthContext,
        *,
        scope: UsageScope = "org",
        from_date: date | None = None,
        to_date: date | None = None,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> UsageStats:
        """When the window's runs happened, by weekday and hour.

        Fills only the envelope and `by_hour`, for the same reason
        :meth:`usage_by_version` fills only its own block: it is a different
        question about the same window, and a hundred and sixty-eight cells do
        not belong in every dashboard load.

        Sparse, and deliberately so - a slot nobody ever ran in is absent, and
        the client draws an empty cell for it.
        """
        where = await self._narrow(
            ctx, scope, agent_id=agent_id, user_id=user_id, group_id=group_id
        )
        window = resolve_window(from_date, to_date)

        rows = await agent_run_repo.runs_by_hour(
            self.db,
            organization_id=ctx.organization_id,
            start=window.start,
            end=window.end,
            where=where,
        )
        return UsageStats(
            from_date=window.from_date,
            to_date=window.to_date,
            scope=scope,
            by_hour=[
                HourCount(weekday=weekday, hour=hour, runs=runs) for weekday, hour, runs in rows
            ],
        )

    async def usage_by_version(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID,
        scope: UsageScope = "org",
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> UsageStats:
        """Per-version rows for one agent - the version-compare card's answer.

        Fills only the envelope and `by_version`: it is a different question
        about the same window, and computing the composed blocks nobody asked
        for would be waste. An agent id from another organization matches no
        rows - the window filter carries the tenant - so the answer is empty
        rather than a probe.
        """
        where = await self._narrow(ctx, scope, agent_id=None, user_id=None)
        window = resolve_window(from_date, to_date)

        rows = await agent_run_repo.usage_by_version(
            self.db,
            organization_id=ctx.organization_id,
            # The subject, not a filter: this aggregate groups one agent's runs
            # by the version that answered them, so the id is its own parameter.
            agent_id=agent_id,
            start=window.start,
            end=window.end,
            where=where,
        )
        version_ids = [version_id for version_id, *_ in rows if version_id is not None]
        ratings: dict[UUID, tuple[int, int]] = {}
        if version_ids:
            ratings = await message_rating_repo.rating_counts_by_version(
                self.db, version_ids=version_ids, start=window.start, end=window.end
            )

        by_version = []
        for version_id, version, runs, completed, p95, avg_cost in rows:
            likes, total = ratings.get(version_id, (0, 0)) if version_id is not None else (0, 0)
            by_version.append(
                VersionUsageRow(
                    agent_version_id=version_id,
                    version=version,
                    runs=runs,
                    completed_runs=completed,
                    p95_ms=round(p95) if p95 is not None else None,
                    avg_cost_usd=avg_cost,
                    like_count=likes,
                    rating_count=total,
                )
            )

        return UsageStats(
            from_date=window.from_date,
            to_date=window.to_date,
            scope=scope,
            agent_id=agent_id,
            by_version=by_version,
        )

    async def usage_by_user(
        self,
        ctx: AuthContext,
        *,
        scope: UsageScope = "org",
        from_date: date | None = None,
        to_date: date | None = None,
        agent_id: UUID | None = None,
        group_id: UUID | None = None,
        limit: int,
    ) -> UsageStats:
        """Per-person rows for the window - the who-is-using-it card's answer.

        Named people, so the scope rule earns its keep here more than
        anywhere else on this endpoint: `scope=org` is refused without
        runs:view, and `scope=own` narrows to the caller, which answers with
        their own single row rather than with everybody's.

        Fills only the envelope and `by_user`, for the same reason
        usage_by_version() does: the card asking this question already holds
        the composed response, and the count it sits under comes from there.
        """
        where = await self._narrow(ctx, scope, agent_id=agent_id, user_id=None, group_id=group_id)
        window = resolve_window(from_date, to_date)

        rows = await agent_run_repo.usage_by_user(
            self.db,
            organization_id=ctx.organization_id,
            start=window.start,
            end=window.end,
            where=where,
            limit=limit,
        )
        return UsageStats(
            from_date=window.from_date,
            to_date=window.to_date,
            scope=scope,
            by_user=[
                PersonUsageRow(
                    user_id=row_user_id,
                    email=email,
                    full_name=full_name,
                    runs=runs,
                    cost_usd=cost,
                    last_run_at=last_run_at,
                )
                for row_user_id, email, full_name, runs, cost, last_run_at in rows
            ],
        )

    async def ratings_summary(
        self,
        ctx: AuthContext,
        *,
        scope: UsageScope = "org",
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> ScopedRatingSummary:
        """Answer quality for the organization, or for the caller's own chats.

        The same scope rule as usage(): org-wide answers demand runs:view,
        the caller's own demand only a caller. Distinct from the app admin's
        deployment-wide summary, which this deliberately does not replace.
        """
        user_id = self._scope_filter(ctx, scope)
        window = resolve_window(from_date, to_date)
        summary = await message_rating_repo.get_rating_summary_scoped(
            self.db,
            organization_id=ctx.organization_id,
            start=window.start,
            end=window.end,
            user_id=user_id,
        )
        return ScopedRatingSummary(
            from_date=window.from_date, to_date=window.to_date, scope=scope, **summary
        )
