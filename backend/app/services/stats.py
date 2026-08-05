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

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal

from app.core.exceptions import AuthorizationError, ValidationError
from app.core.permissions import Perm
from app.repositories import agent_run_repo, member_repo
from app.schemas.stats import (
    ActiveUsers,
    AgentCount,
    CostBlock,
    DayCount,
    LatencyMs,
    ModelCount,
    ProviderCost,
    StatusCount,
    SurfaceCount,
    UsageStats,
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

    async def usage(
        self,
        ctx: AuthContext,
        *,
        scope: UsageScope = "org",
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> UsageStats:
        """The composed answer: totals, slices, latency and cost of one window."""
        user_id = self._scope_filter(ctx, scope)
        window = resolve_window(from_date, to_date)
        prev_start, prev_end = window.previous
        org = ctx.organization_id

        total = await agent_run_repo.count_runs(
            self.db, organization_id=org, start=window.start, end=window.end, user_id=user_id
        )
        previous_total = await agent_run_repo.count_runs(
            self.db, organization_id=org, start=prev_start, end=prev_end, user_id=user_id
        )

        day_counts = dict(
            await agent_run_repo.runs_by_day(
                self.db, organization_id=org, start=window.start, end=window.end, user_id=user_id
            )
        )
        by_day = [
            DayCount(date=day, runs=day_counts.get(day, 0))
            for day in _each_day(window.from_date, window.to_date)
        ]

        by_surface = [
            SurfaceCount(surface=value or "", runs=runs)
            for value, runs in await agent_run_repo.runs_by_dimension(
                self.db,
                organization_id=org,
                start=window.start,
                end=window.end,
                dimension="surface",
                user_id=user_id,
            )
        ]
        by_status = [
            StatusCount(status=value or "", runs=runs)
            for value, runs in await agent_run_repo.runs_by_dimension(
                self.db,
                organization_id=org,
                start=window.start,
                end=window.end,
                dimension="status",
                user_id=user_id,
            )
        ]
        by_model = [
            ModelCount(model_label=value, runs=runs)
            for value, runs in await agent_run_repo.runs_by_dimension(
                self.db,
                organization_id=org,
                start=window.start,
                end=window.end,
                dimension="model",
                user_id=user_id,
            )
        ]
        by_agent = [
            AgentCount(agent_id=agent_id, name=name, runs=runs)
            for agent_id, name, runs in await agent_run_repo.runs_by_agent(
                self.db, organization_id=org, start=window.start, end=window.end, user_id=user_id
            )
        ]

        p50, p95 = await agent_run_repo.latency_percentiles_ms(
            self.db, organization_id=org, start=window.start, end=window.end, user_id=user_id
        )
        latency = LatencyMs(
            p50=round(p50) if p50 is not None else None,
            p95=round(p95) if p95 is not None else None,
        )

        cost = CostBlock(
            period_usd=await agent_run_repo.sum_cost_window(
                self.db, organization_id=org, start=window.start, end=window.end, user_id=user_id
            ),
            previous_period_usd=await agent_run_repo.sum_cost_window(
                self.db, organization_id=org, start=prev_start, end=prev_end, user_id=user_id
            ),
            by_provider=[
                ProviderCost(provider=provider, cost_usd=cost_usd)
                for provider, cost_usd in await agent_run_repo.cost_by_provider_window(
                    self.db,
                    organization_id=org,
                    start=window.start,
                    end=window.end,
                    user_id=user_id,
                )
            ],
        )

        active_users = None
        pending_approvals = None
        if user_id is None:
            active_users = ActiveUsers(
                active=await agent_run_repo.count_distinct_users(
                    self.db, organization_id=org, start=window.start, end=window.end
                ),
                total_members=await member_repo.count_for_org(self.db, org),
            )
        else:
            pending_approvals = await agent_run_repo.count_pending_approval_runs(
                self.db, organization_id=org, user_id=user_id
            )

        return UsageStats(
            from_date=window.from_date,
            to_date=window.to_date,
            scope=scope,
            total_runs=total,
            previous_total_runs=previous_total,
            by_day=by_day,
            by_surface=by_surface,
            by_agent=by_agent,
            by_status=by_status,
            by_model=by_model,
            latency_ms=latency,
            cost=cost,
            active_users=active_users,
            pending_approvals=pending_approvals,
        )
