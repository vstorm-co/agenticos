"""Atomic attachment storage releases capacity on consumption and expiration."""

import asyncio
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.clients.redis import RedisClient
from app.core.background import drain, start_after_rollback, start_deferred
from app.db.models.background_job import BackgroundJob
from app.repositories import background_job as job_repo
from app.services.channels import email_state
from app.services.channels.email import EmailAdapter, queue_delivery
from app.worker.jobs import PROCESS_EMAIL_DELIVERY

pytestmark = pytest.mark.anyio


async def test_cache_admission_is_atomic_and_consumption_releases_exactly_once() -> None:
    redis = RedisClient()
    await redis.connect()
    key = f"test:email-capacity:{uuid4().hex}"
    try:
        decisions = await asyncio.gather(
            *(
                redis.cache_bounded_values(
                    key, values={str(i): "xxxx"}, capacity=10, ttl=60, max_items=20
                )
                for i in range(10)
            )
        )
        assert sum(decisions) == 2
        assert await redis.get(f"{key}:used") == "8"
        accepted = str(decisions.index(True))
        results = await asyncio.gather(
            *(redis.take_bounded_value(key, accepted, ttl=60) for _ in range(10))
        )
        assert results.count("xxxx") == 1
        assert await redis.get(f"{key}:used") == "4"
        assert await redis.cache_bounded_values(
            key, values={"large": "xxxxxx"}, capacity=10, ttl=60, max_items=20
        )
        assert not await redis.cache_bounded_values(
            key, values={"refused": "x"}, capacity=10, ttl=60, max_items=20
        )
        assert await redis.get(f"{key}:file:refused") is None
        assert 0 < await redis.raw.ttl(f"{key}:file:large") <= 60
        for kwargs in (
            {"capacity": 0, "ttl": 60, "max_items": 20},
            {"capacity": 10, "ttl": 0, "max_items": 20},
            {"capacity": 10, "ttl": 60, "max_items": 0},
        ):
            with pytest.raises(ValueError):
                await redis.cache_bounded_values(key, values={"bad": "x"}, **kwargs)
        with pytest.raises(ValueError):
            await redis.take_bounded_value(key, "large", ttl=0)
    finally:
        for handle in [*(str(i) for i in range(10)), "large", "refused"]:
            await redis.take_bounded_value(key, handle, ttl=60)
        await redis.close()


async def test_expired_files_release_capacity_before_the_next_delivery() -> None:
    redis = RedisClient()
    await redis.connect()
    key = f"test:email-expiry:{uuid4().hex}"
    try:
        assert await redis.cache_bounded_values(
            key, values={"old": "xxxx"}, capacity=4, ttl=60, max_items=1
        )
        # Advance this lease past expiry without a wall-clock sleep.
        await redis.raw.zadd(f"{key}:expires", {"old": 0})
        assert await redis.cache_bounded_values(
            key, values={"new": "xxxx"}, capacity=4, ttl=60, max_items=1
        )
        assert await redis.take_bounded_value(key, "old", ttl=60) is None
        assert await redis.get(f"{key}:used") == "4"
        assert await redis.take_bounded_value(key, "new", ttl=60) == "xxxx"
        assert await redis.get(f"{key}:used") is None
        assert await redis.cache_bounded_values(
            key, values={"empty": ""}, capacity=4, ttl=60, max_items=1
        )
        assert not await redis.cache_bounded_values(
            key, values={"other": ""}, capacity=4, ttl=60, max_items=1
        )
    finally:
        for handle in ("old", "new", "empty", "other"):
            await redis.take_bounded_value(key, handle, ttl=60)
        await redis.close()


@pytest.mark.parametrize("commit", [False, True])
async def test_email_receipt_commits_with_its_payload_or_remains_retriable(
    db: AsyncSession, engine: AsyncEngine, commit: bool
) -> None:
    redis = RedisClient()
    await redis.connect()
    email_state.configure(redis)
    bot_id, org_id = uuid4(), uuid4()
    body = json.dumps(
        {
            "from": "ada@example.com",
            "sender_authentication": {"dmarc": "pass", "from": "ada@example.com"},
            "message_id": "<durable-delivery>",
            "text": "Read this file",
            "attachments": [{"content_base64": "aGk="}],
        }
    )
    incoming = EmailAdapter().parse_incoming(json.loads(body), str(bot_id))
    assert incoming is not None
    handles = [item.handle for item in incoming.attachments]

    async def submit() -> bool:
        return await queue_delivery(
            db,
            organization_id=org_id,
            bot_id=bot_id,
            bot_address="bot@example.com",
            body=body,
            incoming=incoming,
        )

    try:
        assert await submit()
        if commit:
            await db.commit()
            start_deferred(db)
        else:
            await db.rollback()
            start_after_rollback(db)
            await drain()
            assert await email_state.take_attachment(handles[0]) is None
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as fresh:
            rows = list(
                await fresh.scalars(
                    select(BackgroundJob).where(BackgroundJob.organization_id == org_id)
                )
            )
        assert len(rows) == int(commit)
        if commit:
            assert rows[0].kind == PROCESS_EMAIL_DELIVERY.kind
            assert rows[0].payload["body"] == body
            # The receipt survives loss of all volatile file content.
            await email_state.discard_attachments(handles)
            assert await submit()
            await db.commit()
            start_deferred(db)
            assert (
                len(
                    list(
                        await db.scalars(
                            select(BackgroundJob).where(BackgroundJob.organization_id == org_id)
                        )
                    )
                )
                == 1
            )
        else:
            assert await submit()
            await db.commit()
            start_deferred(db)
            assert (
                len(
                    list(
                        await db.scalars(
                            select(BackgroundJob).where(BackgroundJob.organization_id == org_id)
                        )
                    )
                )
                == 1
            )
    finally:
        start_deferred(db)
        await email_state.discard_attachments(handles)
        await redis.delete("channel:email:thread:bot@example.com:ada@example.com")
        email_state.configure(None)
        await redis.close()


async def test_concurrent_relay_retries_share_one_committed_receipt(engine: AsyncEngine) -> None:
    redis = RedisClient()
    await redis.connect()
    email_state.configure(redis)
    bot_id, org_id = uuid4(), uuid4()
    body = json.dumps(
        {
            "from": "retry@example.com",
            "sender_authentication": {"dmarc": "pass", "from": "retry@example.com"},
            "message_id": "<same>",
            "text": "hello",
            "attachments": [{"content_base64": "aGk="}],
        }
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    barrier = asyncio.Barrier(2)
    lookup = job_repo.get_by_idempotency_key
    looked_up = 0
    handles: list[str] = []

    async def synchronized_lookup(db, **kwargs):
        nonlocal looked_up
        looked_up += 1
        first = looked_up <= 2
        found = await lookup(db, **kwargs)
        if first:
            await barrier.wait()
        return found

    async def submit() -> None:
        incoming = EmailAdapter().parse_incoming(json.loads(body), str(bot_id))
        assert incoming is not None
        handles.extend(item.handle for item in incoming.attachments)
        async with sessions() as db:
            assert await queue_delivery(
                db,
                organization_id=org_id,
                bot_id=bot_id,
                bot_address="bot@example.com",
                body=body,
                incoming=incoming,
            )
            await db.commit()
            start_deferred(db)

    try:
        with patch.object(job_repo, "get_by_idempotency_key", side_effect=synchronized_lookup):
            async with asyncio.timeout(10):
                await asyncio.gather(submit(), submit())
        async with sessions() as db:
            rows = list(
                await db.scalars(
                    select(BackgroundJob).where(BackgroundJob.organization_id == org_id)
                )
            )
        assert len(rows) == 1
        assert await redis.get(f"channel:email:attachments:{bot_id}:used") == "4"
    finally:
        await email_state.discard_attachments(handles)
        await redis.delete("channel:email:thread:bot@example.com:retry@example.com")
        email_state.configure(None)
        await redis.close()
