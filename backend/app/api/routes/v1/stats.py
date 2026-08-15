"""Usage aggregates - the numbers behind the dashboard.

Deliberately no `require()` here. `scope=own` must be reachable by a plain
member, so the scope decision - org-wide data demands `runs:view`, a caller's
own rows demand only a signed-in membership - is made by
:class:`app.services.stats.StatsService`, which the route-layer sweep
recognizes as resource-aware.
"""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Auth, StatsSvc
from app.core.exceptions import ValidationError
from app.schemas.stats import ScopedRatingSummary, UsageStats

router = APIRouter()


@router.get("/stats/usage", response_model=UsageStats)
async def usage_stats(
    service: StatsSvc,
    ctx: Auth,
    from_: date | None = Query(None, alias="from", description="First day, inclusive (UTC)"),
    to: date | None = Query(None, description="Last day, inclusive (UTC)"),
    scope: Literal["org", "own"] = Query("org"),
    group_by: Literal["version", "user", "hour"] | None = Query(
        None,
        description=(
            "An on-demand dimension instead of the composed response. The"
            " vocabulary is fixed as day | surface | agent | version | user |"
            " status | model | hour | exposure | environment; this release"
            " implements version, user and hour - the composed response already"
            " answers day, surface, agent, status and model, and exposure and"
            " environment land with the Activity page."
        ),
    ),
    agent_id: UUID | None = Query(
        None,
        description=(
            "Narrow every block to one agent. Required when group_by=version,"
            " where it is the subject rather than a filter."
        ),
    ),
    user_id: UUID | None = Query(
        None, description="Narrow every block to one person. Refused with scope=own."
    ),
    limit: int = Query(10, ge=1, le=100, description="Rows to return when group_by=user"),
) -> Any:
    """Runs in a window, sliced every way the dashboard asks at once.

    One composed response on purpose: the cards reading it share one query,
    one loading state and one failure, instead of eight half-loaded answers
    drifting apart. Defaults to the last 30 days; all bucketing is UTC.
    A `group_by` request answers only its own dimension - version-to-version
    comparison is per agent, so it demands an `agent_id`; the per-person
    dimension is org-wide and takes a `limit` instead, because a card cannot
    render five hundred names and an unbounded one would try. `hour` needs
    neither: it is a fixed grid of weekday and hour, sparse where nothing ran.

    `agent_id` and `user_id` narrow the window rather than slicing it, which is
    what lets one dashboard card ask about one agent while the page's own
    filter stays where it is. Narrowing to a colleague reads their rows, so it
    is `scope=org` and behind `runs:view` already; passing one with `scope=own`
    is refused rather than reinterpreted.
    """
    if group_by == "version":
        if agent_id is None:
            raise ValidationError(
                message="group_by=version needs an agent_id",
                details={"group_by": "version"},
            )
        return await service.usage_by_version(
            ctx, agent_id=agent_id, scope=scope, from_date=from_, to_date=to
        )
    if group_by == "user":
        return await service.usage_by_user(
            ctx, scope=scope, from_date=from_, to_date=to, agent_id=agent_id, limit=limit
        )
    if group_by == "hour":
        return await service.usage_by_hour(
            ctx, scope=scope, from_date=from_, to_date=to, agent_id=agent_id, user_id=user_id
        )
    return await service.usage(
        ctx, scope=scope, from_date=from_, to_date=to, agent_id=agent_id, user_id=user_id
    )


@router.get("/ratings/summary", response_model=ScopedRatingSummary)
async def ratings_summary(
    service: StatsSvc,
    ctx: Auth,
    from_: date | None = Query(None, alias="from", description="First day, inclusive (UTC)"),
    to: date | None = Query(None, description="Last day, inclusive (UTC)"),
    scope: Literal["org", "own"] = Query("org"),
) -> Any:
    """Answer quality: the thumbs split and its per-day series.

    `scope=org` is the organization's rated answers, under runs:view;
    `scope=own` is the caller's own conversations, at any role. Distinct from
    `GET /admin/ratings/summary`, which is deployment-wide and app-admin only.
    """
    return await service.ratings_summary(ctx, scope=scope, from_date=from_, to_date=to)
