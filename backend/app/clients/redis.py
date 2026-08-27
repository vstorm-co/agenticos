"""Redis client wrapper.

Provides a class-based Redis client for connection management and operations.
"""

from redis import asyncio as aioredis

from app.core.config import settings


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

    async def delete(self, key: str) -> int:
        """Delete a key. Returns number of keys deleted."""
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.delete(key)  # type: ignore[no-any-return]

    async def getdel(self, key: str) -> str | None:
        """Read a key and delete it in one atomic step (Redis GETDEL).

        A single-use value cannot be read twice: the second reader finds the key
        already gone, so a replayed OAuth exchange code redeems nothing.
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")
        return await self.client.getdel(key)  # ty: ignore[invalid-return-type]

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
