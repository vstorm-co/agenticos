"""Where a person's replayable browse steps are kept - see `browser_use._plans`.

Per person and per organization, and only for a run that is that person
privately - the same line their saved sign-ins draw (`RunAudience.browses_signed_in`),
because the steps say which pages they visit and what they press there. Never
shared with anybody else in the organization, never the text they typed (the
recording stops before it), and gone a fortnight after the task was last done:
a cache, not a record.

Redis rather than the database for that reason, and because a browse runs in the
API for a chat and in the worker for a routine - both reach the same Redis.
"""

import json
import logging
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from app.agents.capabilities.browser_use._plans import PlanStep
from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

TTL_SECONDS = 14 * 24 * 3600
"""How long a plan is kept after the task was last done with it."""

_STEPS = TypeAdapter(tuple[PlanStep, ...])

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


async def connect_in_worker() -> None:
    """Give a worker process a Redis to keep plans in, once - see `live_browse`."""
    global _redis
    if _redis is not None:
        return
    client = RedisClient()
    await client.connect()
    _redis = client


def available() -> bool:
    """Whether this process can keep plans at all - a CLI or a test cannot."""
    return _redis is not None


def _key(organization_id: UUID, user_id: UUID, plan_key: str) -> str:
    return f"browse-plan:{organization_id}:{user_id}:{plan_key}"


async def recall(organization_id: UUID, user_id: UUID, plan_key: str) -> tuple[PlanStep, ...]:
    """The steps this person's last browse of this task took, or none.

    A stored value that no longer reads as steps - written by an older shape of
    them - is no plan rather than a failed browse: it is dropped and the model
    decides every step, as it did before there was one.
    """
    if _redis is None:
        return ()
    raw = await _redis.get(_key(organization_id, user_id, plan_key))
    if raw is None:
        return ()
    try:
        return _STEPS.validate_json(raw)
    except ValidationError:
        logger.warning("browse plan unreadable, dropped")
        await forget(organization_id, user_id, plan_key)
        return ()


async def keep(
    organization_id: UUID, user_id: UUID, plan_key: str, steps: tuple[PlanStep, ...]
) -> None:
    """Keep `steps` for the next time this person asks this task, for a fortnight."""
    if _redis is None or not steps:
        return
    value = json.dumps([step.model_dump(exclude_none=True) for step in steps])
    await _redis.set(_key(organization_id, user_id, plan_key), value, ttl=TTL_SECONDS)


async def forget(organization_id: UUID, user_id: UUID, plan_key: str) -> None:
    """Drop the plan - a replay that did not finish is a recording of a page that changed."""
    if _redis is None:
        return
    await _redis.delete(_key(organization_id, user_id, plan_key))
