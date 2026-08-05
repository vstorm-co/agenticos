"""Usage aggregates - the numbers behind the dashboard.

Deliberately no `require()` here. `scope=own` must be reachable by a plain
member, so the scope decision - org-wide data demands `runs:view`, a caller's
own rows demand only a signed-in membership - is made by
:class:`app.services.stats.StatsService`, which the route-layer sweep
recognizes as resource-aware.
"""

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query

from app.api.deps import Auth, StatsSvc
from app.schemas.stats import UsageStats

router = APIRouter()


@router.get("/stats/usage", response_model=UsageStats)
async def usage_stats(
    service: StatsSvc,
    ctx: Auth,
    from_: date | None = Query(None, alias="from", description="First day, inclusive (UTC)"),
    to: date | None = Query(None, description="Last day, inclusive (UTC)"),
    scope: Literal["org", "own"] = Query("org"),
) -> Any:
    """Runs in a window, sliced every way the dashboard asks at once.

    One composed response on purpose: the cards reading it share one query,
    one loading state and one failure, instead of eight half-loaded answers
    drifting apart. Defaults to the last 30 days; all bucketing is UTC.
    """
    return await service.usage(ctx, scope=scope, from_date=from_, to_date=to)
