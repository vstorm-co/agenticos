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
from app.schemas.stats import UsageStats

router = APIRouter()


@router.get("/stats/usage", response_model=UsageStats)
async def usage_stats(
    service: StatsSvc,
    ctx: Auth,
    from_: date | None = Query(None, alias="from", description="First day, inclusive (UTC)"),
    to: date | None = Query(None, description="Last day, inclusive (UTC)"),
    scope: Literal["org", "own"] = Query("org"),
    group_by: Literal["version"] | None = Query(
        None,
        description=(
            "An on-demand dimension instead of the composed response. The"
            " vocabulary is fixed as day | surface | agent | version | user |"
            " status | model | exposure | environment; this release implements"
            " version - the composed response already answers the first six,"
            " and exposure and environment land with the Activity page."
        ),
    ),
    agent_id: UUID | None = Query(None, description="Required when group_by=version"),
) -> Any:
    """Runs in a window, sliced every way the dashboard asks at once.

    One composed response on purpose: the cards reading it share one query,
    one loading state and one failure, instead of eight half-loaded answers
    drifting apart. Defaults to the last 30 days; all bucketing is UTC.
    A `group_by` request answers only its own dimension - version-to-version
    comparison is per agent, so it demands an `agent_id`.
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
    return await service.usage(ctx, scope=scope, from_date=from_, to_date=to)
