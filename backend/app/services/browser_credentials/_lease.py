"""The API can discover a live owner, but only that owner can write its page."""

import asyncio
import hashlib
from contextlib import suppress
from uuid import UUID

import anyio
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from redis.exceptions import RedisError

from app.clients.redis import RedisClient
from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from app.core.browser_origins import browser_origin
from app.core.browser_session import CredentialGeneration

LEASE_SECONDS = 90
RENEW_SECONDS = 20
REDIS_SECONDS = 5
ORIGIN_SECONDS = 5
_RENEW = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_OBSERVE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  redis.call('set', KEYS[2], ARGV[2], 'EX', ARGV[3])
  return 1
end
return 0
"""
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  redis.call('del', KEYS[1], KEYS[2])
  return 1
end
return 0
"""


class LiveBrowserIdentity(BaseModel):
    """Minted from admitted run dependencies and its frozen capability binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: UUID
    run_id: UUID
    agent_id: UUID
    user_id: UUID
    tab_id: str = Field(min_length=1, max_length=200)
    call_id: str = Field(min_length=1, max_length=200)
    controller_id: UUID
    credential_ids: tuple[UUID, ...] = Field(min_length=1, max_length=50)
    inherited_credentials: tuple[CredentialGeneration, ...] = Field(default=(), max_length=50)


class ObservedOrigin(BaseModel):
    """A short-lived native observation, never an API-supplied destination."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    controller_id: UUID
    tab_id: str = Field(min_length=1, max_length=200)
    origin: str

    _origin = field_validator("origin")(browser_origin)


def _key(run_id: UUID, call_id: str) -> str:
    return f"browser-credential-owner:{run_id}:{hashlib.sha256(call_id.encode()).hexdigest()}"


async def discover(redis: RedisClient, run_id: UUID, call_id: str) -> LiveBrowserIdentity | None:
    try:
        with anyio.fail_after(REDIS_SECONDS):
            raw = await redis.get(_key(run_id, call_id))
        if raw is None or len(raw) > 16384:
            return None
        identity = LiveBrowserIdentity.model_validate_json(raw)
    except RedisError, OSError, TimeoutError, ValidationError:
        return None
    return identity if identity.run_id == run_id and identity.call_id == call_id else None


async def observed_origin(redis: RedisClient, identity: LiveBrowserIdentity) -> str | None:
    try:
        with anyio.fail_after(REDIS_SECONDS):
            raw = await redis.get(_key(identity.run_id, identity.call_id) + ":origin")
        if raw is None or len(raw) > 2048:
            return None
        observed = ObservedOrigin.model_validate_json(raw)
    except RedisError, OSError, TimeoutError, ValidationError:
        return None
    if observed.controller_id != identity.controller_id or observed.tab_id != identity.tab_id:
        return None
    return observed.origin


class BrowserWriterLease:
    """A lost lease is terminal; an old controller never reacquires a page."""

    def __init__(self, redis: RedisClient, identity: LiveBrowserIdentity) -> None:
        self.redis, self.identity = redis, identity
        self._body = identity.model_dump_json()
        self._key = _key(identity.run_id, identity.call_id)
        self._closed = False
        self._lost = False
        self._checking = asyncio.Lock()
        self._heartbeat: asyncio.Task[None] | None = None

    async def acquire(self) -> None:
        if self._closed or self._lost or self._heartbeat is not None:
            raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)
        try:
            with anyio.fail_after(REDIS_SECONDS):
                obtained = await self.redis.set(self._key, self._body, ttl=LEASE_SECONDS, nx=True)
        except RedisError, OSError, TimeoutError:
            self._lost = True
            await self.close()
            raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST) from None
        except asyncio.CancelledError:
            await self.close()
            raise
        if not obtained:
            self._lost = True
            raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)
        self._heartbeat = asyncio.create_task(self._maintain())

    async def observe(self, origin: str) -> None:
        """Publish only while the exact native owner still holds the lease."""
        observed = ObservedOrigin(
            controller_id=self.identity.controller_id, tab_id=self.identity.tab_id, origin=origin
        )
        async with self._checking:
            if self._closed or self._lost:
                raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)
            try:
                with anyio.fail_after(REDIS_SECONDS):
                    published = await self.redis.raw.eval(
                        _OBSERVE,
                        2,
                        self._key,
                        self._key + ":origin",
                        self._body,
                        observed.model_dump_json(),
                        ORIGIN_SECONDS,
                    )
            except RedisError, OSError, TimeoutError:
                self._lost = True
                raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST) from None
            if not published:
                self._lost = True
                raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)

    async def check(self) -> None:
        async with self._checking:
            if self._closed or self._lost:
                raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)
            try:
                with anyio.fail_after(REDIS_SECONDS):
                    renewed = await self.redis.raw.eval(
                        _RENEW, 1, self._key, self._body, LEASE_SECONDS
                    )
            except RedisError, OSError, TimeoutError:
                self._lost = True
                raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST) from None
            if not renewed:
                self._lost = True
                raise BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)

    async def _maintain(self) -> None:
        try:
            while True:
                await asyncio.sleep(RENEW_SECONDS)
                await self.check()
        except BrowserFillRefused:
            return

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with anyio.move_on_after(REDIS_SECONDS + 1, shield=True):
            if self._heartbeat is not None:
                self._heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await self._heartbeat
            with suppress(RedisError, OSError, TimeoutError):
                await self.redis.raw.eval(_RELEASE, 2, self._key, self._key + ":origin", self._body)
