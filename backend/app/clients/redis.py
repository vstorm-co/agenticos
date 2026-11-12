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

_RESERVE_NUMBERS = """
local now = tonumber(redis.call('TIME')[1])
local count = tonumber(ARGV[1])
local highest = tonumber(ARGV[2])
local pending = cjson.decode(redis.call('GET', KEYS[3]) or '{}')
local pruned = false
for code, _ in pairs(pending) do
  local issued = redis.call('ZSCORE', KEYS[2], code)
  if not issued then
    redis.call('ZADD', KEYS[2], 'NX', now, code)
  elseif tonumber(issued) + tonumber(ARGV[5]) < now then
    pending[code] = nil
    pruned = true
  end
end
if pruned then
  if next(pending) == nil then
    redis.call('DEL', KEYS[3])
  else
    redis.call('SET', KEYS[3], cjson.encode(pending), 'KEEPTTL')
  end
end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - tonumber(ARGV[3]))
local last = tonumber(redis.call('GET', KEYS[1]) or '0')
for step = 0, highest - 1 do
  local start = (last + step) % highest + 1
  if start + count - 1 <= highest then
    local free = true
    for n = start, start + count - 1 do
      if pending[tostring(n)] or redis.call('ZSCORE', KEYS[2], n) then
        free = false
        break
      end
    end
    if free then
      for n = start, start + count - 1 do
        redis.call('ZADD', KEYS[2], now, n)
      end
      redis.call('SET', KEYS[1], start + count - 1, 'EX', ARGV[4])
      redis.call('EXPIRE', KEYS[2], ARGV[4])
      return start
    end
  end
end
return 0
"""

_NUMBERED_ANSWER = """
local value = cjson.decode(redis.call('GET', KEYS[1]) or '{}')[ARGV[1]]
if not value then
  return false
end
local issued = redis.call('ZSCORE', KEYS[2], ARGV[1])
if issued and tonumber(issued) + tonumber(ARGV[2]) < tonumber(redis.call('TIME')[1]) then
  return false
end
return value
"""

_PRUNE_BOUNDED_VALUES = """
local now = tonumber(redis.call('TIME')[1])
local used = tonumber(redis.call('GET', KEYS[3]) or '0')
for _, handle in ipairs(redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now)) do
  used = used - tonumber(redis.call('HGET', KEYS[1], handle) or '0')
  redis.call('HDEL', KEYS[1], handle)
  redis.call('ZREM', KEYS[2], handle)
  redis.call('DEL', ARGV[1] .. handle)
end
used = math.max(0, used)
local function save()
  if redis.call('HLEN', KEYS[1]) == 0 then
    redis.call('DEL', KEYS[1], KEYS[2], KEYS[3])
  else
    redis.call('SET', KEYS[3], used, 'EX', ARGV[2])
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    redis.call('EXPIRE', KEYS[2], ARGV[2])
  end
end
"""

_CACHE_BOUNDED_VALUES = (
    _PRUNE_BOUNDED_VALUES
    + """
local amount = 0
local added = 0
for i = 5, #ARGV, 2 do
  local previous = redis.call('HGET', KEYS[1], ARGV[i])
  amount = amount + #ARGV[i + 1] - tonumber(previous or '0')
  if not previous then added = added + 1 end
end
if used + amount > tonumber(ARGV[3]) or
  redis.call('HLEN', KEYS[1]) + added > tonumber(ARGV[4]) then
  save()
  return 0
end
for i = 5, #ARGV, 2 do
  redis.call('SET', ARGV[1] .. ARGV[i], ARGV[i + 1], 'EX', ARGV[2])
  redis.call('HSET', KEYS[1], ARGV[i], #ARGV[i + 1])
  redis.call('ZADD', KEYS[2], now + tonumber(ARGV[2]), ARGV[i])
end
used = used + amount
save()
return 1
"""
)

_TAKE_BOUNDED_VALUE = (
    _PRUNE_BOUNDED_VALUES
    + """
local value = redis.call('GETDEL', ARGV[1] .. ARGV[3])
used = math.max(0, used - tonumber(redis.call('HGET', KEYS[1], ARGV[3]) or '0'))
redis.call('HDEL', KEYS[1], ARGV[3])
redis.call('ZREM', KEYS[2], ARGV[3])
save()
return value
"""
)

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

    async def reserve_numbers(
        self,
        counter: str,
        *,
        issued: str,
        pending: str,
        count: int,
        highest: int,
        quarantine: int,
        answerable: int,
        ttl: int,
    ) -> int:
        """Reserve `count` consecutive numbers from 1 to `highest`, or return 0 when none are free.

        The block starts after the last one reserved and wraps around, skipping a number
        still named in the JSON object at `pending` or reserved within `quarantine`
        seconds - `issued` holds when each was. A number in `pending` reserved over
        `answerable` seconds ago no longer answers, so it is dropped from `pending` first;
        one with no reservation time is stamped now and lapses in turn. Reserving nothing
        changes nothing else.
        """
        result = await self.raw.eval(
            _RESERVE_NUMBERS,
            3,
            counter,
            issued,
            pending,
            count,
            highest,
            quarantine,
            ttl,
            answerable,
        )
        if not isinstance(result, int):
            raise TypeError("Redis returned an invalid number reservation")
        return result

    async def numbered_answer(
        self, mapping: str, *, issued: str, number: str, ttl: int
    ) -> str | None:
        """What `number` names in the JSON object at `mapping`, unless it was reserved over
        `ttl` seconds ago, by the Redis clock `reserve_numbers` stamps it with."""
        result = await self.raw.eval(_NUMBERED_ANSWER, 2, mapping, issued, number, ttl)
        if result is None:
            return None
        return result.decode() if isinstance(result, bytes) else str(result)

    async def cache_bounded_values(
        self, key: str, *, values: dict[str, str], capacity: int, ttl: int, max_items: int
    ) -> bool:
        """Store a batch atomically; expired or consumed entries never retain capacity."""
        if capacity <= 0 or ttl <= 0 or max_items <= 0:
            raise ValueError("Bounded caches require positive capacity, TTL and item limit")
        if not values:
            return True
        entries = [part for handle, value in values.items() for part in (handle, value)]
        stored = await self.raw.eval(
            _CACHE_BOUNDED_VALUES,
            3,
            f"{key}:sizes",
            f"{key}:expires",
            f"{key}:used",
            f"{key}:file:",
            ttl,
            capacity,
            max_items,
            *entries,
        )
        return bool(stored)

    async def take_bounded_value(self, key: str, handle: str, *, ttl: int) -> str | None:
        """Consume and release an entry exactly once, including concurrent readers."""
        if ttl <= 0:
            raise ValueError("Bounded caches require a positive TTL")
        value = await self.raw.eval(
            _TAKE_BOUNDED_VALUE,
            3,
            f"{key}:sizes",
            f"{key}:expires",
            f"{key}:used",
            f"{key}:file:",
            ttl,
            handle,
        )
        if value is not None and not isinstance(value, str):
            raise TypeError("Redis returned invalid cached text")
        return value

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
