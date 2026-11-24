"""A live socket and exact human takeover must both survive before capture is accepted."""

import hashlib
from contextlib import suppress
from uuid import UUID

import anyio
from pydantic import Field, ValidationError
from redis.exceptions import RedisError

from app.clients.redis import RedisClient
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingModel,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
)

LEASE_SECONDS = 60
RENEW_SECONDS = 15
REDIS_SECONDS = 3
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


class BrowserProcedureTeachingRunIdentity(BrowserProcedureTeachingModel):
    organization_id: UUID
    run_id: UUID
    agent_id: UUID
    user_id: UUID


class BrowserProcedureTeachingIdentity(BrowserProcedureTeachingRunIdentity):
    controller_id: UUID
    tab_id: str = Field(min_length=1, max_length=200)
    call_id: str = Field(min_length=1, max_length=200)


class BrowserProcedureTeachingTakeover(BrowserProcedureTeachingIdentity):
    connection_id: UUID
    takeover_id: UUID


def connection_key(run_id: str, call_id: str, connection_id: UUID) -> str:
    return (
        f"browser-control:{run_id}:{hashlib.sha256(call_id.encode()).hexdigest()}:{connection_id}"
    )


async def open_connection(
    redis: RedisClient, run_id: str, call_id: str, connection_id: UUID, user_id: str
) -> bool:
    try:
        with anyio.fail_after(REDIS_SECONDS):
            return bool(
                await redis.set(
                    connection_key(run_id, call_id, connection_id),
                    user_id,
                    ttl=LEASE_SECONDS,
                    nx=True,
                )
            )
    except RedisError, OSError, TimeoutError:
        return False


async def renew_connection(
    redis: RedisClient, run_id: str, call_id: str, connection_id: UUID, user_id: str
) -> bool:
    try:
        with anyio.fail_after(REDIS_SECONDS):
            return bool(
                await redis.raw.eval(
                    _RENEW,
                    1,
                    connection_key(run_id, call_id, connection_id),
                    user_id,
                    LEASE_SECONDS,
                )
            )
    except RedisError, OSError, TimeoutError:
        return False


async def close_connection(
    redis: RedisClient, run_id: str, call_id: str, connection_id: UUID, user_id: str
) -> None:
    with anyio.move_on_after(REDIS_SECONDS, shield=True):
        with suppress(RedisError, OSError, TimeoutError):
            await redis.raw.eval(
                _RELEASE, 1, connection_key(run_id, call_id, connection_id), user_id
            )


def _key(run_id: UUID, call_id: str) -> str:
    return f"browser-teaching-owner:{run_id}:{hashlib.sha256(call_id.encode()).hexdigest()}"


async def _connection_alive(redis: RedisClient, identity: BrowserProcedureTeachingTakeover) -> bool:
    return await redis.get(
        connection_key(str(identity.run_id), identity.call_id, identity.connection_id)
    ) == str(identity.user_id)


async def discover(
    redis: RedisClient, run_id: UUID, call_id: str
) -> BrowserProcedureTeachingTakeover | None:
    try:
        with anyio.fail_after(REDIS_SECONDS):
            raw = await redis.get(_key(run_id, call_id))
            if raw is None or len(raw) > 4096:
                return None
            identity = BrowserProcedureTeachingTakeover.model_validate_json(raw)
            if (
                identity.run_id != run_id
                or identity.call_id != call_id
                or not await _connection_alive(redis, identity)
            ):
                return None
            return identity
    except RedisError, OSError, TimeoutError, ValidationError:
        return None


class BrowserProcedureTeachingLease:
    """No reacquisition after a lost socket, takeover or controller identity."""

    def __init__(self, redis: RedisClient, identity: BrowserProcedureTeachingTakeover) -> None:
        self.redis, self.identity = redis, identity
        self._body = identity.model_dump_json()
        self._key = _key(identity.run_id, identity.call_id)
        self._lost = False
        self._closed = False

    async def acquire(self) -> None:
        if self._lost or self._closed:
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)
        try:
            with anyio.fail_after(REDIS_SECONDS):
                alive = await _connection_alive(self.redis, self.identity)
                acquired = alive and await self.redis.set(
                    self._key, self._body, ttl=LEASE_SECONDS, nx=True
                )
        except RedisError, OSError, TimeoutError:
            acquired = False
        if not acquired:
            self._lost = True
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)

    async def check(self) -> None:
        if self._closed or self._lost:
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)
        try:
            with anyio.fail_after(REDIS_SECONDS):
                alive = await _connection_alive(self.redis, self.identity)
                renewed = alive and await self.redis.raw.eval(
                    _RENEW, 1, self._key, self._body, LEASE_SECONDS
                )
        except RedisError, OSError, TimeoutError:
            renewed = False
        if not renewed:
            self._lost = True
            raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OWNERSHIP_LOST)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with anyio.move_on_after(REDIS_SECONDS, shield=True):
            with suppress(RedisError, OSError, TimeoutError):
                await self.redis.raw.eval(_RELEASE, 1, self._key, self._body)
