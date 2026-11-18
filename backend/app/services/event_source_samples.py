"""Ephemeral captures on the live source URL, independent of dispatch."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import TypeAdapter
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.background import spawn_after_commit
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.schemas.event_source import JsonObject, SourceCapture, SourceListening, SourceSample
from app.services.event_sources import EventSourceService
from app.services.workflow_webhook_test import KEEP_SECONDS, LISTEN_SECONDS
from app.workflows.graph.model import pinned_output_fits

logger = logging.getLogger(__name__)
_TOKENS = TypeAdapter(dict[str, str])
_LISTENING = SourceCapture(state="listening").model_dump_json()


class EventSourceSampleService:
    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db = db
        self.redis = redis

    async def listen(self, ctx: AuthContext, source_id: UUID) -> SourceListening:
        await EventSourceService(self.db).require_use(ctx, source_id)
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=LISTEN_SECONDS)
        owner = f"{ctx.organization_id}:{ctx.subject_id}:{source_id}"
        await self.redis.set(
            f"source:listener:{token}:owner", owner, ttl=KEEP_SECONDS + LISTEN_SECONDS
        )
        await self.redis.set(f"source:listener:{token}:state", _LISTENING, ttl=LISTEN_SECONDS)
        await self.redis.update_mapping(
            f"source:listeners:{source_id}",
            updates={token: str(expires.timestamp())},
            ttl=LISTEN_SECONDS,
        )
        return SourceListening(listener_id=token, expires_at=expires)

    async def caught(self, ctx: AuthContext, source_id: UUID, token: str) -> SourceCapture:
        await EventSourceService(self.db).require_use(ctx, source_id)
        owner = await self.redis.get(f"source:listener:{token}:owner")
        if owner != f"{ctx.organization_id}:{ctx.subject_id}:{source_id}":
            raise NotFoundError(message="Listener not found")
        state = await self.redis.get(f"source:listener:{token}:state")
        return (
            SourceCapture.model_validate_json(state)
            if state is not None
            else SourceCapture(state="expired")
        )

    def capture_after_commit(self, source_id: UUID, *, body: JsonObject, delivery_id: str) -> None:
        """Keep the optional Redis capture outside the delivery transaction."""
        spawn_after_commit(
            self.db,
            capture_source_sample(self.redis, source_id, body=body, delivery_id=delivery_id),
            name="event-source-sample",
        )


async def capture_source_sample(
    redis: RedisClient, source_id: UUID, *, body: JsonObject, delivery_id: str
) -> None:
    """A cache outage or an oversized capture must never change live admission."""
    try:
        raw = await redis.get(f"source:listeners:{source_id}")
        if not raw:
            return
        tokens = _TOKENS.validate_json(raw)
        delivery = SourceSample(body=body, delivery_id=delivery_id)
        try:
            pinned_output_fits(delivery.model_dump(mode="json"))
        except ValueError:
            sample = SourceCapture(state="too_large")
        else:
            sample = SourceCapture(state="caught", delivery=delivery)
        captured = sample.model_dump_json()
        now = datetime.now(UTC).timestamp()
        for token, expires in tokens.items():
            if float(expires) <= now:
                continue
            await redis.replace_if_equal(
                f"source:listener:{token}:state",
                expected=_LISTENING,
                value=captured,
                ttl=KEEP_SECONDS,
            )
        await redis.update_mapping(
            f"source:listeners:{source_id}", updates={}, remove=list(tokens), ttl=LISTEN_SECONDS
        )
    except RedisError, OSError, ValueError, RecursionError:
        logger.warning("event_source_sample_cache_unavailable")
