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
    handles: list[str] = []

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


@pytest.mark.parametrize("platform", ["sms", "imessage"])
async def test_sms_and_imessage_receipts_are_durable_and_rollback_remains_retriable(
    db: AsyncSession, engine: AsyncEngine, platform: str
) -> None:
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from app.db.models.channel_bot import ChannelBot
    from app.services.channel_bot import ChannelBotService
    from app.services.channels.imessage import ImessageAdapter
    from app.services.channels.sms import SmsAdapter
    from app.worker.jobs import ChannelDelivery
    from app.worker.tasks import channel_tasks

    bot = ChannelBot(
        id=uuid4(),
        organization_id=uuid4(),
        platform=platform,
        name="Inbox",
        is_active=True,
        webhook_mode=True,
    )
    payload = (
        {"From": "+15559998888", "Body": "hello", "MessageSid": "SM-durable"}
        if platform == "sms"
        else {
            "type": "new-message",
            "data": {
                "guid": "durable-guid",
                "text": "hello",
                "isFromMe": False,
                "handle": {"address": "ada@example.com"},
                "chats": [{"guid": "iMessage;-;ada@example.com"}],
            },
        }
    )
    adapter = SmsAdapter() if platform == "sms" else ImessageAdapter()
    incoming = adapter.parse_incoming(payload, str(bot.id))
    assert incoming is not None
    try:
        await ChannelBotService(db).queue_delivery(bot, payload, incoming)
        await db.rollback()
        assert (
            await db.scalar(
                select(BackgroundJob).where(BackgroundJob.organization_id == bot.organization_id)
            )
            is None
        )
        await ChannelBotService(db).queue_delivery(bot, payload, incoming)
        await db.commit()
        await ChannelBotService(db).queue_delivery(bot, payload, incoming)
        await db.commit()
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as fresh:
            rows = list(
                await fresh.scalars(
                    select(BackgroundJob).where(
                        BackgroundJob.organization_id == bot.organization_id
                    )
                )
            )
        assert len(rows) == 1 and rows[0].payload["payload"] == payload

        @asynccontextmanager
        async def connection():
            async with sessions() as fresh:
                yield fresh

        with (
            patch.object(channel_tasks, "get_db_context", connection),
            patch(
                "app.repositories.channel_bot_repo.get_for_inbound", new=AsyncMock(return_value=bot)
            ),
            patch.object(channel_tasks, "_route_inbound", new=AsyncMock()) as routed,
        ):
            await channel_tasks.process_channel_delivery(
                ChannelDelivery.model_validate(rows[0].payload)
            )
        routed.assert_awaited_once()
        assert routed.await_args.args[0].platform == platform
    finally:
        await adapter.aclose()


@pytest.mark.parametrize("quota", ["bytes", "jobs"])
async def test_retained_email_quota_covers_text_duplicates_and_completed_receipts(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, quota: str
) -> None:
    from unittest.mock import AsyncMock

    from app.services.channels import email as email_module

    monkeypatch.setattr(email_module, "keep_inbound", AsyncMock(return_value=object()))
    organization, bot = uuid4(), uuid4()
    body = json.dumps(
        {
            "from": "ada@example.com",
            "sender_authentication": {"dmarc": "pass", "from": "ada@example.com"},
            "text": "x" * 100,
            "message_id": "first",
        }
    )
    first = EmailAdapter().parse_incoming(json.loads(body), str(bot))
    assert first is not None and not first.attachments
    monkeypatch.setattr(
        email_module,
        "MAX_RETAINED_DELIVERY_BYTES" if quota == "bytes" else "MAX_RETAINED_DELIVERIES",
        len(body.encode()) if quota == "bytes" else 1,
    )
    arguments = {
        "organization_id": organization,
        "bot_id": bot,
        "bot_address": "bot@example.com",
        "body": body,
        "incoming": first,
    }
    assert await queue_delivery(db, **arguments)
    receipt = (await db.scalars(select(BackgroundJob))).one()
    receipt.status = "succeeded"
    await db.flush()
    assert await queue_delivery(db, **arguments)
    second = EmailAdapter().parse_incoming(json.loads(body.replace("first", "other")), str(bot))
    assert second is not None
    assert not await queue_delivery(db, **{**arguments, "incoming": second})
    assert await queue_delivery(db, **{**arguments, "organization_id": uuid4(), "incoming": second})
    assert len(list(await db.scalars(select(BackgroundJob)))) == 2


async def test_concurrent_email_admission_cannot_exceed_retained_job_quota(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.services.channels import email as email_module

    monkeypatch.setattr(email_module, "MAX_RETAINED_DELIVERIES", 1)
    monkeypatch.setattr(email_module, "keep_inbound", AsyncMock(return_value=object()))
    organization, bot = uuid4(), uuid4()

    async def admit(identifier: str) -> bool:
        body = json.dumps(
            {
                "from": "ada@example.com",
                "sender_authentication": {"dmarc": "pass", "from": "ada@example.com"},
                "text": "Mail",
                "message_id": identifier,
            }
        )
        incoming = EmailAdapter().parse_incoming(json.loads(body), str(bot))
        assert incoming is not None
        async with AsyncSession(engine) as db:
            accepted = await queue_delivery(
                db,
                organization_id=organization,
                bot_id=bot,
                bot_address="bot@example.com",
                body=body,
                incoming=incoming,
            )
            await db.commit()
            return accepted

    assert sorted(await asyncio.gather(admit("one"), admit("two"))) == [False, True]
