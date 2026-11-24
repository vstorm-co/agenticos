"""The confirmed human-control lease, shared between the run's worker and the API.

The browse loop knows who holds a tab, but it runs in a worker process. When
the run's own person takes a tab over, the capture writes a short-lived Redis
record naming organization, run, agent, person, view and a fresh `hold_id`.
It renews the record while the hold lasts and deletes it on hand-back. The API
reads it to start or resume recording, and capture re-reads it before every
accepted event. A lost record is a lost lease: nothing re-creates it except a
new take-over, which gets a new `hold_id`.
"""

import hashlib
import logging
from contextlib import suppress
from uuid import UUID

import anyio
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import RedisError

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

HOLD_SECONDS = 45
RENEW_SECONDS = 15
_REDIS_SECONDS = 3
_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class Hold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: UUID
    run_id: UUID
    agent_id: UUID
    user_id: UUID
    call_id: str = Field(min_length=1, max_length=200)
    tab_id: str = Field(min_length=1, max_length=200)
    hold_id: UUID


def _key(run_id: UUID, call_id: str) -> str:
    return f"browser-teaching:hold:{run_id}:{hashlib.sha256(call_id.encode()).hexdigest()}"


async def claim(redis: RedisClient, hold: Hold) -> bool:
    try:
        with anyio.fail_after(_REDIS_SECONDS):
            return await redis.set(
                _key(hold.run_id, hold.call_id), hold.model_dump_json(), ttl=HOLD_SECONDS, nx=True
            )
    except (RedisError, OSError, TimeoutError) as exc:
        logger.warning("Browser teaching hold not claimed (%s)", type(exc).__name__)
        return False


async def renew(redis: RedisClient, hold: Hold) -> bool:
    try:
        with anyio.fail_after(_REDIS_SECONDS):
            return bool(
                await redis.raw.eval(
                    _RENEW, 1, _key(hold.run_id, hold.call_id), hold.model_dump_json(), HOLD_SECONDS
                )
            )
    except (RedisError, OSError, TimeoutError) as exc:
        logger.warning("Browser teaching hold not renewed (%s)", type(exc).__name__)
        return False


async def release(redis: RedisClient, hold: Hold) -> None:
    with anyio.move_on_after(_REDIS_SECONDS, shield=True), suppress(RedisError, OSError):
        await redis.raw.eval(_RELEASE, 1, _key(hold.run_id, hold.call_id), hold.model_dump_json())


async def current(redis: RedisClient, run_id: UUID, call_id: str) -> Hold | None:
    """The live hold on this view, or `None` when nobody holds it or Redis cannot say."""
    try:
        with anyio.fail_after(_REDIS_SECONDS):
            raw = await redis.get(_key(run_id, call_id))
        if raw is None or len(raw) > 2048:
            return None
        hold = Hold.model_validate_json(raw)
    except (RedisError, OSError, TimeoutError, ValidationError) as exc:
        logger.warning("Browser teaching hold unreadable (%s)", type(exc).__name__)
        return None
    return hold if hold.run_id == run_id and hold.call_id == call_id else None
