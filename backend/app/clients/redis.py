"""Redis client wrapper.

Provides a class-based Redis client for connection management and operations.
"""

import json
from collections.abc import Sequence

from redis import asyncio as aioredis

from app.core.config import settings

_DELETE_IF_EQUALS = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""

_DELETE_IF_EQUAL = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)

_RESERVE_RANGE = """
local last = math.max(tonumber(redis.call('get', KEYS[1]) or '0'), tonumber(ARGV[1]))
redis.call('set', KEYS[1], last + tonumber(ARGV[2]), 'EX', ARGV[3])
return last + 1
"""

_RESERVE_CAPACITY = """
local used = tonumber(redis.call('get', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
if used + amount > tonumber(ARGV[2]) then return 0 end
redis.call('set', KEYS[1], used + amount, 'EX', ARGV[3])
return 1
"""

_UPDATE_MAPPING = """
local values = cjson.decode(redis.call('get', KEYS[1]) or '{}')
for key, value in pairs(cjson.decode(ARGV[1])) do values[key] = value end
for _, key in ipairs(cjson.decode(ARGV[2])) do values[key] = nil end
if next(values) == nil then
  redis.call('del', KEYS[1])
else
  redis.call('set', KEYS[1], cjson.encode(values), 'EX', ARGV[3])
end
return 1
"""


class RedisClient:
    """Redis client wrapper for connection lifecycle management.

    Usage in FastAPI lifespan:
        async with contextmanager():
            redis = RedisClient(settings.REDIS_URL)
            await redis.connect()
            yield {"redis": redis}
            await redis.close()
    """

    def __init__(self, url: str | None = None):
        self.url = url or settings.REDIS_URL
        self.client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis server."""
        self.client = aioredis.from_url(  # type: ignore[no-untyped-call]
            self.url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def close(self) -> None:
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            self.client = None

    async def get(self, key: str) -> str | None:
        """Get a value by key."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        # `bytes` to the stubs, `str` at runtime: `connect` passes
        # `decode_responses=True`, which redis-py cannot express in a return type.
        return await self.client.get(key)  # ty: ignore[invalid-return-type]

    async def set(
        self,
        key: str,
        value: str,
        ttl: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Set a value with optional TTL (in seconds).

        With `nx=True` the write happens only when the key does not already
        exist - Redis `SET NX`, one atomic claim - and the return value says
        whether this call was the one that wrote it. Redis answers a refused
        NX write with a nil reply, which the driver surfaces as `None`.
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return bool(await self.client.set(key, value, ex=ttl, nx=nx))

    async def count_in_window(self, key: str, ttl: int) -> int:
        """Count one hit in a fixed window, and answer how many it now holds.

        `INCR` then `EXPIRE … NX`, pipelined: the increment creates the key when
        the window is new and the conditional expiry gives it a lifetime without
        ever extending an existing one. `NX` is what makes it a *fixed* window -
        a plain `EXPIRE` on every hit would push the deadline out with each call,
        so a caller who never stops never resets, and their allowance would be
        gone until they did.

        Redis 7 or newer, which every compose file pins.
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        used, _expired = await pipe.execute()
        return int(used)

    async def expire(self, key: str, ttl: int) -> bool:
        """Set a key's lifetime to `ttl` seconds. False when there is no such key."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return bool(await self.client.expire(key, ttl))

    async def reserve_range(self, key: str, *, minimum: int, count: int, ttl: int) -> int:
        """Reserve consecutive numbers atomically, retaining failed-delivery gaps until expiry."""
        result = await self.raw.eval(_RESERVE_RANGE, 1, key, minimum, count, ttl)
        if not isinstance(result, int):
            raise TypeError("Redis returned an invalid number reservation")
        return result

    async def reserve_capacity(self, key: str, *, amount: int, capacity: int, ttl: int) -> bool:
        """Reserve a bounded amount atomically until the last accepted reservation expires."""
        if amount <= 0 or capacity <= 0 or ttl <= 0:
            raise ValueError("Capacity reservations require positive amounts, capacity and TTL")
        reserved = await self.raw.eval(_RESERVE_CAPACITY, 1, key, amount, capacity, ttl)
        return bool(reserved)

    async def update_mapping(
        self, key: str, *, updates: dict[str, str], remove: Sequence[str] = (), ttl: int
    ) -> None:
        """Merge/remove JSON fields atomically without losing concurrent prompt changes."""
        await self.raw.eval(
            _UPDATE_MAPPING, 1, key, json.dumps(updates), json.dumps(list(remove)), ttl
        )

    async def delete_if_equal(self, key: str, value: str) -> bool:
        """Delete a key only while it still holds `value` - a lease given back by its holder."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        # The stubs union a sync and an async return; this client is the async one.
        deleted = await self.client.eval(_DELETE_IF_EQUAL, 1, key, value)  # ty: ignore[invalid-await]
        return bool(deleted)

    async def delete(self, key: str) -> int:
        """Delete a key. Returns number of keys deleted."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.delete(key)  # type: ignore[no-any-return]

    async def delete_if_equals(self, key: str, value: str) -> bool:
        """Delete `key` only while it still holds `value`, in one atomic step.

        How a claim taken with `set(..., nx=True)` is released by its own holder
        alone: a holder that outlived the key's TTL finds another holder's value
        there and leaves it. Returns whether this call deleted the key.
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")
        deleted = await self.client.eval(_DELETE_IF_EQUALS, 1, key, value)
        return bool(deleted)

    async def getdel(self, key: str) -> str | None:
        """Read a key and delete it in one atomic step (Redis GETDEL).

        A single-use value cannot be read twice: the second reader finds the key
        already gone, so a replayed OAuth exchange code redeems nothing.
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.getdel(key)  # ty: ignore[invalid-return-type]

    async def pop_left(self, key: str) -> str | None:
        """Take the first item of a list, or `None` when it is empty (Redis LPOP)."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        # `bytes` to the stubs, `str` at runtime - see `get`.
        return await self.client.lpop(key)  # ty: ignore[invalid-return-type]

    async def wait_pop_left(self, key: str, timeout: float) -> str | None:
        """Take the first item of a list, waiting up to `timeout` seconds (BLPOP).

        Holds one pooled connection while it waits, so callers keep the timeout
        short and call again.
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")
        # The stubs union a sync and an async return; this client is the async one.
        popped = await self.client.blpop([key], timeout=timeout)  # ty: ignore[invalid-await]
        return None if popped is None else str(popped[1])

    async def list_range(self, key: str) -> list[str]:
        """Every item of a list, oldest first (Redis LRANGE 0 -1)."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        # The stubs union a sync and an async return; this client is the async one.
        items = await self.client.lrange(key, 0, -1)  # ty: ignore[invalid-await]
        return [str(item) for item in items]

    async def hash_all(self, key: str) -> dict[str, str]:
        """Every field of a hash, and its value (Redis HGETALL)."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        # The stubs union a sync and an async return; this client is the async one.
        fields = await self.client.hgetall(key)  # ty: ignore[invalid-await]
        return {str(field): str(value) for field, value in fields.items()}

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return bool(await self.client.exists(key))

    async def ping(self) -> bool:
        """Ping Redis server. Returns True if connected."""
        if not self.client:
            return False
        try:
            await self.client.ping()
            return True
        except Exception:
            return False

    @property
    def raw(self) -> aioredis.Redis:
        """Access the underlying aioredis client for advanced operations."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return self.client
