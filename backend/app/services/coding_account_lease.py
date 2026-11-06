"""Serialize tasks using one renewable credential across API and worker processes."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

import anyio

from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.exceptions import ConflictError


@asynccontextmanager
async def account_lease(
    key: str, timeout_seconds: int, *, redis: RedisClient | None = None
) -> AsyncGenerator[None]:
    owned = redis is None
    client = redis if redis is not None else RedisClient(str(settings.REDIS_URL))
    token = uuid4().hex
    try:
        if owned:
            await client.connect()
        if not await client.set(key, token, ttl=timeout_seconds + 1800, nx=True):
            raise ConflictError(
                message="This coding account already has a task running. Try again when it finishes."
            )
        try:
            yield
        finally:
            with anyio.CancelScope(shield=True):
                await client.delete_if_equal(key, token)
    finally:
        if owned:
            with anyio.CancelScope(shield=True):
                await client.close()
