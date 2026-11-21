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
from app.schemas.event_source import (
    EventSourceTarget,
    JsonObject,
    SourceCapture,
    SourceListening,
    SourceSample,
)
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

    async def listen(
        self, ctx: AuthContext, source_id: UUID, target: EventSourceTarget
    ) -> SourceListening:
        sources = EventSourceService(self.db)
        await sources.require_use(ctx, source_id)
        await sources.require_target(ctx, target)
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=LISTEN_SECONDS)
        owner = f"{ctx.organization_id}:{ctx.subject_id}:{source_id}"
        await self.redis.set(
            f"source:listener:{token}:{owner}:target",
            target.model_dump_json(),
            ttl=KEEP_SECONDS + LISTEN_SECONDS,
        )
        await self.redis.set(f"source:listener:{token}:state", _LISTENING, ttl=LISTEN_SECONDS)
        await self.redis.update_mapping(
            f"source:listeners:{source_id}",
            updates={token: str(expires.timestamp())},
            ttl=LISTEN_SECONDS,
        )
        return SourceListening(listener_id=token, expires_at=expires)

    async def caught(self, ctx: AuthContext, source_id: UUID, token: str) -> SourceCapture:
        sources = EventSourceService(self.db)
        await sources.require_use(ctx, source_id)
        owner = f"{ctx.organization_id}:{ctx.subject_id}:{source_id}"
        target = await self.redis.get(f"source:listener:{token}:{owner}:target")
        if target is None:
            raise NotFoundError(message="Listener not found")
        await sources.require_target(ctx, EventSourceTarget.model_validate_json(target))
        state = await self.redis.get(f"source:listener:{token}:state")
        return (
            SourceCapture.model_validate_json(state)
            if state is not None
            else SourceCapture(state="expired")
        )

    def capture_after_commit(
        self, source_id: UUID, *, body: JsonObject, delivery_id: str, received_at: datetime
    ) -> None:
        """Keep the optional Redis capture outside the delivery transaction."""
        spawn_after_commit(
            self.db,
            capture_source_sample(
                self.redis, source_id, body=body, delivery_id=delivery_id, received_at=received_at
            ),
            name="event-source-sample",
        )


async def capture_source_sample(
    redis: RedisClient,
    source_id: UUID,
    *,
    body: JsonObject,
    delivery_id: str,
    received_at: datetime,
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
        received = received_at.timestamp()
        finished: list[str] = []
        for token, expires in tokens.items():
            deadline = float(expires)
            if now >= deadline:
                finished.append(token)
            elif received >= deadline - LISTEN_SECONDS:
                await redis.replace_if_equal(
                    f"source:listener:{token}:state",
                    expected=_LISTENING,
                    value=captured,
                    ttl=KEEP_SECONDS,
                )
                finished.append(token)
        if finished:
            await redis.update_mapping(
                f"source:listeners:{source_id}", updates={}, remove=finished, ttl=LISTEN_SECONDS
            )
    except RedisError, OSError, ValueError, RecursionError:
        logger.warning("event_source_sample_cache_unavailable")
