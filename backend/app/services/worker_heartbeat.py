"""When each of the worker's in-process sweeps last finished a tick (#2213).

The sweeps run inside the worker's own process (`app/worker/sweeps.py`), so a
tick leaves no Prefect flow run behind to be counted. Each one leaves this
instead, and `health.probe_scheduler` reads it from the API process - the two
processes share Redis and nothing else that would do.
"""

from datetime import datetime

from app.clients.redis import RedisClient

SWEEPS = (
    "agent-triggers-check",
    "portal-poll",
    "notification-delivery-sweep",
    "rag-sync-check",
    "sandbox-destroy-retry",
)
"""Every sweep `app/worker/prefect_app.py` runs, by name - each records on its own."""

_KEY = "worker:sweep:{}"

TTL_SECONDS = 7 * 86_400
"""Long enough to say "last ran three days ago" rather than "never" after an outage."""


async def record(redis: RedisClient, sweep: str, at: datetime) -> None:
    """Say `sweep` finished a tick at `at`."""
    await redis.set(_KEY.format(sweep), at.isoformat(), ttl=TTL_SECONDS)


async def last(redis: RedisClient, sweep: str) -> datetime | None:
    """When `sweep` last finished a tick, or `None` for never - or for a value nothing wrote."""
    raw = await redis.get(_KEY.format(sweep))
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
