"""Native context and delivery receipts use real PostgreSQL uniqueness and fencing."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import background_job as jobs
from app.repositories import conversation as conversations
from app.services.background_jobs import enqueue
from app.services.conversation import ConversationService
from app.worker.jobs import (
    DELIVER_CHANNEL_REPLY,
    PROCESS_CHANNEL_MESSAGE,
    ChannelHandback,
    ChannelMessage,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("kind", "status", "submission_started", "updated"),
    [
        ("deliver-channel-reply", "queued", False, True),
        ("deliver-channel-reply", "queued", True, False),
        ("deliver-channel-reply", "running", False, False),
        ("process-channel-message", "queued", False, False),
    ],
)
async def test_rendered_reply_changes_only_an_unclaimed_delivery(
    db: AsyncSession, kind: str, status: str, submission_started: bool, updated: bool
) -> None:
    row = BackgroundJob(
        kind=kind,
        pool="agent",
        status=status,
        max_attempts=1,
        payload={"output": "Saved answer", "submission_started": submission_started},
    )
    db.add(row)
    await db.flush()

    await jobs.render_channel_reply(db, job_id=row.id, output="Saved answer with usage")
    await db.refresh(row)

    assert row.payload == {
        "output": "Saved answer with usage" if updated else "Saved answer",
        "submission_started": submission_started,
    }


async def test_thread_context_is_imported_once_and_replayed_by_the_shared_history(
    db: AsyncSession,
) -> None:
    user = User(email="thread-test@example.test", hashed_password="unused", full_name="Thread test")
    db.add(user)
    await db.flush()
    org = Organization(name="Thread test", slug="thread-test", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    conversation = Conversation(organization_id=org.id)
    db.add(conversation)
    await db.flush()
    args = {
        "conversation_id": conversation.id,
        "source_id": "native-1",
        "content": "We agreed on Friday.",
        "identity_id": None,
        "posted_at": datetime(2026, 11, 16, tzinfo=UTC),
    }
    assert await conversations.add_channel_reference(db, **args)
    assert not await conversations.add_channel_reference(db, **args)
    history = await ConversationService(db).model_history(conversation.id, limit=200)
    assert len(history) == 1
    assert "We agreed on Friday." in str(history[0])
    assert "2026-11-16" in str(history[0])
    assert "Thread reference, posted" in str(history[0])
    assert await conversations.known_channel_posts(
        db, conversation_id=conversation.id, source_ids=["native-1", "other"]
    ) == {"native-1"}
    other = Conversation(organization_id=org.id)
    db.add(other)
    await db.flush()
    assert await conversations.add_channel_reference(db, **{**args, "conversation_id": other.id})


async def test_a_final_answer_is_claimed_once_and_records_transport_separately(
    db: AsyncSession,
) -> None:
    payload = ChannelHandback(
        initial_reply_id=uuid4(),
        organization_id=uuid4(),
        run_id=uuid4(),
        bot_id=uuid4(),
        platform_chat_id="room:thread",
        private_chat=False,
        output="Saved answer",
    )
    job_id = await enqueue(db, DELIVER_CHANNEL_REPLY, payload)
    assert job_id is not None
    assert await jobs.claim_channel_reply(db, job_id=job_id)
    assert not await jobs.claim_channel_reply(db, job_id=job_id)
    await jobs.settle_channel_reply(db, job_id=job_id, delivered=False)
    record = await jobs.get_channel_reply(db, reply_id=payload.initial_reply_id)
    assert record is not None and record.status == "dead"
    assert record.result == {"delivery": "unconfirmed"}
    assert record.max_attempts == 1
    await jobs.settle_channel_reply(db, job_id=job_id, delivered=True)
    await db.refresh(record)
    assert record.status == "dead" and record.result == {"delivery": "unconfirmed"}
    assert await jobs.get_channel_reply(db, reply_id=None) is None


async def test_steering_consumes_only_the_same_senders_unstarted_messages(db: AsyncSession) -> None:
    organization_id, bot_id, generation = uuid4(), uuid4(), uuid4()
    first_id = None
    for sender in ("alice", "bob"):
        payload = ChannelMessage(
            receipt_id=uuid4(),
            organization_id=organization_id,
            bot_id=bot_id,
            authorization_generation=generation,
            platform="mattermost",
            platform_user_id=sender,
            platform_chat_id="room:thread",
            chat_type="group",
            text="Use Friday",
            message_id=sender,
        )
        job_id = await enqueue(
            db,
            PROCESS_CHANNEL_MESSAGE,
            payload,
            organization_id=organization_id,
            concurrency_key="thread",
        )
        if sender == "alice":
            first_id = job_id
    additions = await jobs.queued_channel_additions(
        db, organization_id=organization_id, concurrency_key="thread", sender="alice"
    )
    assert [item.id for item in additions] == [first_id]
    assert first_id is not None
    run_id = uuid4()
    await jobs.finish_channel_addition(db, job_id=first_id, run_id=run_id)
    assert not await jobs.queued_channel_additions(
        db, organization_id=organization_id, concurrency_key="thread", sender="alice"
    )
    assert (
        len(
            await jobs.queued_channel_additions(
                db, organization_id=organization_id, concurrency_key="thread", sender="bob"
            )
        )
        == 1
    )
    assert not await jobs.queued_channel_additions(
        db, organization_id=uuid4(), concurrency_key="thread", sender="bob"
    )


async def test_an_expired_or_unstarted_job_cannot_steer_as_the_active_worker(
    db: AsyncSession,
) -> None:
    receipt = uuid4()
    row = BackgroundJob(
        kind="process-channel-message",
        pool="agent",
        payload={"receipt_id": str(receipt)},
        status="queued",
        max_attempts=1,
    )
    db.add(row)
    await db.flush()
    assert not await jobs.channel_message_is_running(db, receipt_id=receipt)
    assert not await jobs.lock_channel_message_lease(db, receipt_id=receipt)
    row.status, row.lease_until = "running", datetime.now(UTC) + timedelta(minutes=1)
    await db.flush()
    assert await jobs.channel_message_is_running(db, receipt_id=receipt)
    assert await jobs.lock_channel_message_lease(db, receipt_id=receipt)
    row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    assert not await jobs.channel_message_is_running(db, receipt_id=receipt)
    assert not await jobs.lock_channel_message_lease(db, receipt_id=receipt)


async def test_consumed_native_receipts_survive_compaction(db: AsyncSession) -> None:
    from sqlalchemy import delete

    from app.db.models.conversation import Message

    user = User(email="compaction@example.test", hashed_password="unused", full_name="Test")
    db.add(user)
    await db.flush()
    org = Organization(name="Compaction", slug="compaction", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    conversation = Conversation(organization_id=org.id)
    db.add(conversation)
    await db.flush()
    assert await conversations.add_channel_reference(
        db,
        conversation_id=conversation.id,
        source_id="old-post",
        content="Already summarized",
        identity_id=None,
        posted_at=None,
    )
    await db.execute(delete(Message).where(Message.conversation_id == conversation.id))
    assert not await conversations.add_channel_reference(
        db,
        conversation_id=conversation.id,
        source_id="old-post",
        content="Already summarized",
        identity_id=None,
        posted_at=None,
    )
    # A steer is already carried by the run's own parts; remembering its native
    # id must not append another copy to the transcript.
    assert await conversations.remember_channel_source(
        db, conversation_id=conversation.id, source_id="steer"
    )
    assert not await conversations.add_channel_reference(
        db,
        conversation_id=conversation.id,
        source_id="steer",
        content="Use Friday",
        identity_id=None,
        posted_at=None,
    )
    assert not await ConversationService(db).model_history(conversation.id, limit=200)


async def test_erasure_removes_durable_messages_from_the_linked_native_sender(
    db: AsyncSession,
) -> None:
    from sqlalchemy import select

    from app.db.models.channel_identity import ChannelIdentity
    from app.repositories import personal_data_repo

    user = User(email="erase-queue@example.test", hashed_password="unused", full_name="Test")
    db.add(user)
    await db.flush()
    db.add(ChannelIdentity(platform="mattermost", platform_user_id="alice", user_id=user.id))
    own = BackgroundJob(
        kind="process-channel-message",
        pool="agent",
        max_attempts=1,
        payload={"platform": "mattermost", "platform_user_id": "alice", "text": "private words"},
    )
    other = BackgroundJob(
        kind="process-channel-message",
        pool="agent",
        max_attempts=1,
        payload={"platform": "mattermost", "platform_user_id": "bob", "text": "other words"},
    )
    db.add_all([own, other])
    await db.flush()
    await personal_data_repo.purge_identities_of(db, user.id)
    assert list((await db.scalars(select(BackgroundJob.id))).all()) == [other.id]


async def test_two_workers_do_not_run_the_same_thread_together(engine) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    payload = ChannelMessage(
        receipt_id=uuid4(),
        organization_id=uuid4(),
        bot_id=uuid4(),
        authorization_generation=uuid4(),
        platform="mattermost",
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text="first",
        message_id="first",
    )
    async with factory.begin() as db:
        first = await enqueue(db, PROCESS_CHANNEL_MESSAGE, payload, concurrency_key="one-thread")
    async with factory.begin() as db:
        second = await enqueue(
            db,
            PROCESS_CHANNEL_MESSAGE,
            payload.model_copy(update={"receipt_id": uuid4(), "message_id": "second"}),
            concurrency_key="one-thread",
        )
    async with factory.begin() as db:
        claimed = await jobs.claim(
            db, pool="agent", worker_id="worker-1", lease=timedelta(minutes=1)
        )
        assert claimed is not None and claimed.id == first
    async with factory.begin() as db:
        assert (
            await jobs.claim(db, pool="agent", worker_id="worker-2", lease=timedelta(minutes=1))
            is None
        )
        assert await jobs.complete(db, claimed.id, fence=claimed.attempts)
    async with factory.begin() as db:
        next_job = await jobs.claim(
            db, pool="agent", worker_id="worker-2", lease=timedelta(minutes=1)
        )
        assert next_job is not None and next_job.id == second


async def test_new_migration_matches_the_postgres_models(engine) -> None:
    import importlib.util
    from pathlib import Path

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.db.base import Base

    path = Path(__file__).parents[2] / "alembic/versions/0333_channel_thread_context.py"
    spec = importlib.util.spec_from_file_location("channel_pg_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def verify(connection):
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
            migration.upgrade()
        assert compare_metadata(context, Base.metadata) == []

    async with engine.begin() as connection:
        await connection.run_sync(verify)


async def test_native_turn_receipts_and_controls_are_bound_to_the_actual_sender(
    db: AsyncSession,
) -> None:
    from app.db.models.agent import Agent
    from app.db.models.agent_run import AgentRun
    from app.db.models.channel_identity import ChannelIdentity
    from app.db.models.conversation import Message
    from app.repositories import agent_run_repo

    user = User(email="controls@example.test", hashed_password="unused", full_name="Test")
    db.add(user)
    await db.flush()
    org = Organization(name="Controls", slug="controls", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(organization_id=org.id, name="QA", slug="qa", draft_spec={})
    conversation = Conversation(organization_id=org.id)
    alice = ChannelIdentity(platform="mattermost", platform_user_id="alice")
    bob = ChannelIdentity(platform="mattermost", platform_user_id="bob")
    db.add_all([agent, conversation, alice, bob])
    await db.flush()
    now = datetime.now(UTC)
    older = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        channel_identity_id=alice.id,
        created_at=now - timedelta(seconds=1),
    )
    root = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        channel_identity_id=alice.id,
        created_at=now,
    )
    other = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        channel_identity_id=bob.id,
        created_at=now + timedelta(seconds=1),
    )
    db.add_all([older, root, other])
    await db.flush()
    child = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        channel_identity_id=alice.id,
        parent_run_id=root.id,
        created_at=now + timedelta(seconds=2),
    )
    db.add(child)
    await db.flush()
    found = await agent_run_repo.latest_for_channel_sender(
        db, organization_id=org.id, conversation_id=conversation.id, identity_id=alice.id
    )
    assert found is not None and found.id == root.id
    completed_aside = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        channel_identity_id=alice.id,
        status="completed",
        created_at=now + timedelta(seconds=3),
    )
    db.add(completed_aside)
    await db.flush()
    active = await agent_run_repo.latest_for_channel_sender(
        db,
        organization_id=org.id,
        conversation_id=conversation.id,
        identity_id=alice.id,
        prefer_running=True,
    )
    assert active is not None and active.id == root.id
    assert (
        await agent_run_repo.latest_for_channel_sender(
            db, organization_id=uuid4(), conversation_id=conversation.id, identity_id=alice.id
        )
        is None
    )
    assert (
        await agent_run_repo.latest_for_channel_sender(
            db, organization_id=org.id, conversation_id=None, identity_id=alice.id
        )
        is None
    )
    await agent_run_repo.request_channel_stop(db, run=root)
    assert root.channel_stop_requested_at is not None and other.channel_stop_requested_at is None
    db.add_all(
        [
            Message(
                conversation_id=conversation.id, run_id=root.id, role="user", content="Question"
            ),
            Message(
                conversation_id=conversation.id, run_id=root.id, role="assistant", content="Answer"
            ),
        ]
    )
    await db.flush()
    await conversations.bind_channel_source(db, run_id=root.id, role="user", source_id="question")
    await conversations.bind_channel_source(
        db, run_id=root.id, role="assistant", source_id="answer"
    )
    await conversations.bind_channel_source(db, run_id=root.id, role="assistant", source_id=None)
    await conversations.bind_channel_source(
        db, run_id=uuid4(), role="assistant", source_id="not-posted"
    )
    assert await conversations.known_channel_posts(
        db, conversation_id=conversation.id, source_ids=["question", "answer", "not-posted"]
    ) == {"question", "answer"}


@pytest.mark.parametrize("platform", ["slack", "mattermost", "telegram", "discord"])
async def test_native_redeliveries_are_durable_and_thread_queues_stay_isolated(
    db: AsyncSession, platform: str
) -> None:
    from dataclasses import replace

    from sqlalchemy import select

    from app.db.models.channel_bot import ChannelBot
    from app.services.channels.base import IncomingMessage
    from app.services.channels.ingress import conversation_queue, queue_message

    bot = ChannelBot(
        id=uuid4(),
        organization_id=uuid4(),
        authorization_generation=uuid4(),
        platform=platform,
        access_policy={"discord_guild_ids": ["123456789"]},
        name="Queue test",
        token_encrypted="unused",
        secret_key_version=1,
    )
    other_bot = ChannelBot(
        id=uuid4(),
        organization_id=bot.organization_id,
        authorization_generation=uuid4(),
        platform=platform,
        access_policy={"discord_guild_ids": ["123456789"]},
        name="Other queue",
        token_encrypted="unused",
        secret_key_version=1,
    )
    incoming = IncomingMessage(
        platform=platform,
        bot_id=str(bot.id),
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text="Use Friday",
        message_id="native-1",
        addressed=True,
        raw={"token": "must-not-persist", "guild_id": "123456789"},
    )
    await queue_message(db, bot, incoming)
    await queue_message(db, bot, incoming)
    await queue_message(db, bot, replace(incoming, message_id="native-2"))
    await queue_message(db, bot, replace(incoming, platform_chat_id="room:other"))
    await queue_message(db, other_bot, replace(incoming, bot_id=str(other_bot.id)))
    rows = list(
        await db.scalars(
            select(BackgroundJob).where(
                BackgroundJob.organization_id == bot.organization_id,
                BackgroundJob.kind == PROCESS_CHANNEL_MESSAGE.kind,
            )
        )
    )
    assert len(rows) == 4
    assert (
        sum(
            row.payload["message_id"] == "native-1"
            and row.payload["bot_id"] == str(bot.id)
            and row.payload["platform_chat_id"] == "room:thread"
            for row in rows
        )
        == 1
    )
    original = conversation_queue(bot.id, "room:thread")
    assert [row.concurrency_key for row in rows].count(original) == 2
    assert {row.concurrency_key for row in rows} == {
        original,
        conversation_queue(bot.id, "room:other"),
        conversation_queue(other_bot.id, "room:thread"),
    }
    assert all("must-not-persist" not in str(row.payload) for row in rows)


@pytest.mark.parametrize("control,limit", [(True, 8), (False, 100)])
async def test_channel_queue_caps_are_scoped_to_bot_and_organization(
    db: AsyncSession, control, limit
):
    org, bot = uuid4(), uuid4()
    kind = "process-channel-control" if control else "process-channel-message"
    db.add_all(
        [
            BackgroundJob(
                kind=kind,
                pool="system" if control else "agent",
                organization_id=org,
                max_attempts=1,
                payload={"bot_id": str(bot)},
            )
            for _ in range(limit)
        ]
    )
    await db.flush()
    assert not await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=control, size=10
    )
    assert await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=uuid4(), control=control, size=10
    )
    assert await jobs.channel_queue_has_room(
        db, organization_id=uuid4(), bot_id=bot, control=control, size=10
    )
    assert await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=not control, size=10
    )


@pytest.mark.parametrize("control", [True, False])
async def test_channel_queue_caps_payload_bytes_even_before_the_count_limit(
    db: AsyncSession, control
):
    org, bot = uuid4(), uuid4()
    size = 32 * 1024 if control else 2 * 1024 * 1024
    db.add(
        BackgroundJob(
            kind="process-channel-control" if control else "process-channel-message",
            pool="agent",
            organization_id=org,
            max_attempts=1,
            payload={"bot_id": str(bot), "text": "x" * size},
        )
    )
    await db.flush()
    assert not await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=control, size=1
    )


@pytest.mark.parametrize("status", ["succeeded", "dead", "cancelled"])
@pytest.mark.parametrize("quota", ["count", "bytes"])
async def test_terminal_channel_payloads_keep_their_quota_until_cleanup(
    db: AsyncSession, status: str, quota: str
) -> None:
    org, bot = uuid4(), uuid4()
    for _ in range(1_000 if quota == "count" else 1):
        db.add(
            BackgroundJob(
                kind="process-channel-control",
                pool="system",
                organization_id=org,
                status=status,
                max_attempts=1,
                payload={
                    "bot_id": str(bot),
                    "text": "x" * (2 * 1024 * 1024 if quota == "bytes" else 1),
                },
            )
        )
    await db.flush()

    assert not await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=True, size=1
    )
    assert await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=uuid4(), control=True, size=1
    )
    assert await jobs.channel_queue_has_room(
        db, organization_id=uuid4(), bot_id=bot, control=True, size=1
    )
    assert await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=False, size=1
    )

    await db.execute(delete(BackgroundJob).where(BackgroundJob.organization_id == org))
    assert await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=True, size=1
    )


@pytest.mark.parametrize(
    "ending",
    [
        "complete",
        "fail",
        "bury",
        "release",
        "cancel",
        "cancel_payload",
        "rescue",
        "live_ok",
        "live_failed",
    ],
)
async def test_finished_reply_jobs_discard_duplicate_answer_bodies(
    db: AsyncSession, ending: str
) -> None:
    run_id, org = uuid4(), uuid4()
    row = BackgroundJob(
        kind="deliver-channel-reply",
        organization_id=org,
        pool="system",
        status="queued"
        if ending in {"cancel", "cancel_payload", "live_ok", "live_failed"}
        else "running",
        attempts=1,
        max_attempts=1,
        lease_until=datetime.now(UTC) - timedelta(seconds=1),
        payload={
            "run_id": str(run_id),
            "submission_started": True,
            "output": "Duplicate answer body",
            "tool_calls": [{"args": {"query": "Large tool input"}, "result": "Large tool result"}],
            "generated_files": ["report.pdf"],
        },
    )
    db.add(row)
    await db.flush()
    match ending:
        case "complete":
            assert await jobs.complete(db, row.id, fence=1)
        case "fail":
            assert (
                await jobs.fail(db, row.id, fence=1, error="failed", retry_in=timedelta())
                == jobs.FailOutcome.DEAD
            )
        case "bury":
            assert await jobs.bury(db, row.id, fence=1, error="invalid")
        case "release":
            assert await jobs.release(db, row.id, fence=1) == "dead"
        case "cancel":
            assert await jobs.cancel_queued(db, row.id)
        case "cancel_payload":
            assert (
                await jobs.cancel_queued_for_payload(
                    db,
                    kind=row.kind,
                    organization_id=org,
                    payload_key="run_id",
                    payload_value=run_id,
                )
                == 1
            )
        case "rescue":
            rescued = await jobs.rescue_expired(db, retry_in=timedelta())
            assert any(job.id == row.id for job in rescued)
        case _:
            await jobs.settle_channel_reply(db, job_id=row.id, delivered=ending == "live_ok")
    await db.refresh(row)

    assert row.status in {"succeeded", "dead", "cancelled"}
    assert row.payload == {
        "run_id": str(run_id),
        "submission_started": True,
        "output": "",
        "tool_calls": [],
        "generated_files": [],
    }


async def test_unfinished_or_unowned_reply_attempts_keep_the_recovery_snapshot(
    db: AsyncSession,
) -> None:
    payload = {
        "output": "Pending answer",
        "tool_calls": [{"result": "Evidence"}],
        "generated_files": [],
    }
    row = BackgroundJob(
        kind="deliver-channel-reply",
        pool="system",
        status="running",
        attempts=1,
        max_attempts=2,
        payload=payload,
    )
    db.add(row)
    await db.flush()
    assert not await jobs.complete(db, row.id, fence=2)
    assert (
        await jobs.fail(db, row.id, fence=1, error="temporary", retry_in=timedelta())
        == jobs.FailOutcome.RETRYING
    )
    await db.refresh(row)
    assert row.status == "queued" and row.payload == payload


async def test_pending_reply_bodies_count_until_terminal_settlement(db: AsyncSession) -> None:
    org, bot = uuid4(), uuid4()
    row = BackgroundJob(
        kind="deliver-channel-reply",
        pool="system",
        organization_id=org,
        status="running",
        attempts=1,
        max_attempts=1,
        payload={"bot_id": str(bot), "output": "x" * (32 * 1024 * 1024)},
    )
    db.add(row)
    await db.flush()
    assert not await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=False, size=1
    )
    assert await jobs.complete(db, row.id, fence=1)
    assert await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=False, size=1
    )


async def test_an_admitted_edit_survives_receipt_expiry_and_queues_only_once(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from app.db.models.channel_bot import ChannelBot
    from app.services.channels import ingress, router
    from app.services.channels.base import IncomingMessage

    bot = ChannelBot(
        id=uuid4(),
        organization_id=uuid4(),
        authorization_generation=uuid4(),
        is_active=True,
        access_policy={},
    )
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(bot.id),
        platform_user_id="alice",
        platform_chat_id="room:thread",
        chat_type="group",
        text="@bot help",
        message_id="original",
        addressed=True,
        raw={"event": "post_edited"},
    )
    eligible = AsyncMock(return_value=True)
    monkeypatch.setattr(ingress, "edited_delivery_is_eligible", eligible)
    monkeypatch.setattr(router.ChannelMessageRouter, "_check_rate_limit", AsyncMock())
    await ingress.queue_message(db, bot, incoming)
    eligible.return_value = False
    await ingress.queue_message(db, bot, replace(incoming, text="@bot changed again"))
    rows = (
        await db.scalars(
            select(BackgroundJob).where(BackgroundJob.organization_id == bot.organization_id)
        )
    ).all()
    assert len(rows) == 1
    admitted = ingress.restore(ChannelMessage.model_validate(rows[0].payload))
    assert admitted.edit_admitted

    claim = AsyncMock(
        side_effect=AssertionError("The durable edit no longer needs its expired Redis receipt")
    )
    deliver = AsyncMock()
    monkeypatch.setattr(router, "claim_delivery", claim)
    monkeypatch.setattr(router.ChannelMessageRouter, "_route_inner", deliver)
    await router.ChannelMessageRouter().route(admitted, db)
    deliver.assert_awaited_once()
    claim.assert_not_awaited()


async def test_recovered_reply_leaves_terminal_transition_to_the_fenced_worker(
    db: AsyncSession, monkeypatch
):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from app.worker.tasks import channel_tasks

    payload = ChannelHandback(
        initial_reply_id=uuid4(),
        organization_id=uuid4(),
        run_id=uuid4(),
        bot_id=uuid4(),
        platform_chat_id="room:thread",
        private_chat=False,
        output="Rendered answer\n\n_Cost: $0.03_",
    )
    job_id = await enqueue(db, DELIVER_CHANNEL_REPLY, payload)
    claimed = await jobs.claim(
        db, pool=DELIVER_CHANNEL_REPLY.pool.value, worker_id="recovery", lease=timedelta(minutes=1)
    )
    assert claimed is not None and claimed.id == job_id
    # The live route may not steal a job already held by recovery.
    assert not await jobs.claim_channel_reply(db, job_id=job_id)

    @asynccontextmanager
    async def context():
        yield db

    monkeypatch.setattr(channel_tasks, "get_db_context", context)
    monkeypatch.setattr(channel_tasks, "deliver_handback", AsyncMock(return_value=True))
    await channel_tasks.deliver_initial_reply(payload)
    record = await jobs.get_channel_reply(db, reply_id=payload.initial_reply_id)
    assert record is not None
    await db.refresh(record)
    assert record.status == "running" and record.worker_id == "recovery"
    assert await jobs.complete(db, claimed.id, fence=claimed.attempts, result=None)
    await db.refresh(record)
    assert (
        record.status == "succeeded"
        and record.worker_id == "recovery"
        and record.lease_until is None
    )


@pytest.mark.parametrize(
    "control,by_bytes", [(False, False), (True, False), (False, True), (True, True)]
)
async def test_one_sender_cannot_spend_another_senders_retained_quota(
    db: AsyncSession, control: bool, by_bytes: bool
) -> None:
    org, bot = uuid4(), uuid4()
    count = 1 if by_bytes else (100 if control else 1000)
    size = (256 * 1024 if control else 4 * 1024 * 1024) if by_bytes else 0
    db.add_all(
        [
            BackgroundJob(
                kind="process-channel-control" if control else "process-channel-message",
                pool="system" if control else "agent",
                status="succeeded",
                max_attempts=1,
                organization_id=org,
                payload={"bot_id": str(bot), "platform_user_id": "alice", "text": "x" * size},
            )
            for _ in range(count)
        ]
    )
    await db.flush()
    assert not await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=control, size=1, sender="alice"
    )
    assert await jobs.channel_queue_has_room(
        db, organization_id=org, bot_id=bot, control=control, size=1, sender="bob"
    )
