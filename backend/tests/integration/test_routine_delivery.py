"""A resumed answer survives its process and reaches an authorized chat once."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation, Message
from app.db.models.notification import Notification
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.repositories import routine_delivery as delivery_repo
from app.services.agent_trigger import AgentTriggerService
from app.services.routine_delivery import RoutineDeliveryService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class World:
    org: Organization
    user: User
    member: OrganizationMember
    agent: Agent
    trigger: AgentTrigger
    chat: Conversation
    run: AgentRun


@pytest.fixture
async def world(db: AsyncSession) -> World:
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    member = OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")
    agent = Agent(
        organization_id=org.id,
        owner_user_id=user.id,
        status="published",
        name="Report",
        slug=f"report-{uuid4()}",
    )
    db.add_all([agent, member])
    await db.flush()
    version = AgentVersion(agent_id=agent.id, organization_id=org.id, version=1, spec={})
    chat = Conversation(organization_id=org.id, user_id=user.id, title="Original private chat")
    db.add_all([version, chat])
    await db.flush()
    agent.current_version_id = version.id
    trigger = AgentTrigger(
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        name="My report",
        prompt="Report",
        interval_seconds=300,
        next_fire_at=datetime.now(UTC),
        answer_to="conversation",
        delivery_conversation_id=chat.id,
    )
    db.add(trigger)
    await db.flush()
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=user.id,
        conversation_id=None,
        surface="schedule",
        model_label="test",
        started_at=datetime.now(UTC),
        trigger_id=trigger.id,
        routine_origin_id=trigger.id,
        routine_kind="trigger",
        initiated_by_publisher_fallback=True,
    )
    run.status = RunStatus.COMPLETED.value
    run.ended_at = datetime.now(UTC)
    trigger.last_run_id = run.id
    trigger.last_delivery_status = "not_completed"
    await db.flush()
    return World(org, user, member, agent, trigger, chat, run)


async def messages(db: AsyncSession, world: World) -> list[Message]:
    return list(await db.scalars(select(Message).where(Message.run_id == world.run.id)))


@pytest.mark.parametrize("one_shot", [False, True])
async def test_a_durable_answer_is_delivered_once_after_a_restart(
    db: AsyncSession, world: World, one_shot: bool
) -> None:
    world.trigger.one_shot = one_shot
    service = RoutineDeliveryService(db)
    await service.queue(world.run, answer="Final approved result")
    await service.queue(world.run, answer="Do not replace the admitted result")
    (job,) = list(
        await db.scalars(
            select(BackgroundJob).where(BackgroundJob.kind == "deliver-routine-answer")
        )
    )
    assert job.payload == {"organization_id": str(world.org.id), "run_id": str(world.run.id)}
    org_id, run_id = world.org.id, world.run.id
    await db.commit()
    db.expunge_all()
    await AgentTriggerService(db).deliver_resumed_answer(org_id, run_id)
    await db.commit()
    await AgentTriggerService(db).deliver_resumed_answer(org_id, run_id)
    (message,) = await messages(db, world)
    assert message.conversation_id == world.chat.id
    assert message.content == "**My report**\n\nFinal approved result"
    receipt = await delivery_repo.get(db, run_id=run_id, organization_id=org_id)
    assert receipt is not None and receipt.status == "delivered"
    assert receipt.conversation_id == world.chat.id
    assert len(
        list(
            await db.scalars(select(Notification).where(Notification.event_type == "run_completed"))
        )
    ) == int(not one_shot)


@pytest.mark.parametrize(
    "change",
    [
        "paused",
        "expired",
        "removed",
        "inactive",
        "other-owner",
        "archived-chat",
        "wrong-org",
        "agent-grant",
        "archived-agent",
    ],
)
async def test_pending_answers_recheck_current_delivery_authority(
    db: AsyncSession, world: World, change: str
) -> None:
    await RoutineDeliveryService(db).queue(world.run, answer="Private result")
    if change == "paused":
        world.trigger.is_active = False
    elif change == "expired":
        world.trigger.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "removed":
        await db.delete(world.trigger)
    elif change == "inactive":
        world.user.is_active = False
    elif change == "other-owner":
        other = User(email=f"{uuid4()}@example.com", hashed_password="x")
        db.add(other)
        await db.flush()
        world.chat.user_id = other.id
    elif change == "archived-chat":
        world.chat.is_archived = True
    elif change == "agent-grant":
        world.member.role = "viewer"
    elif change == "archived-agent":
        world.agent.status = "archived"
    await db.flush()
    await AgentTriggerService(db).deliver_resumed_answer(
        uuid4() if change == "wrong-org" else world.org.id, world.run.id
    )
    assert await messages(db, world) == []
    receipt = await delivery_repo.get(db, run_id=world.run.id, organization_id=world.org.id)
    assert receipt is not None
    assert receipt.status == ("pending" if change == "wrong-org" else "unavailable")


async def test_two_delivery_attempts_cannot_append_two_messages(
    db: AsyncSession, engine: AsyncEngine, world: World
) -> None:
    await RoutineDeliveryService(db).queue(world.run, answer="One result")
    org_id, run_id = world.org.id, world.run.id
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt() -> None:
        async with sessions() as session:
            await AgentTriggerService(session).deliver_resumed_answer(org_id, run_id)
            await session.commit()

    await asyncio.gather(attempt(), attempt())
    assert len(await messages(db, world)) == 1


async def test_delivery_database_failure_leaves_the_handoff_retryable(
    db: AsyncSession, world: World
) -> None:
    from sqlalchemy.exc import DBAPIError

    await RoutineDeliveryService(db).queue(world.run, answer="Keep this result")

    async def failed_write(*args: object, **kwargs: object) -> None:
        await db.execute(text("select 1 / 0"))

    with (
        patch("app.services.agent_trigger.conversation_repo.create_message", new=failed_write),
        pytest.raises(DBAPIError),
    ):
        await AgentTriggerService(db).deliver_resumed_answer(world.org.id, world.run.id)
    receipt = await delivery_repo.get(db, run_id=world.run.id, organization_id=world.org.id)
    assert receipt is not None and receipt.status == "pending"
    assert await messages(db, world) == []
    await AgentTriggerService(db).deliver_resumed_answer(world.org.id, world.run.id)
    assert len(await messages(db, world)) == 1


@pytest.mark.parametrize("status", ["awaiting_approval", "awaiting_answer", "failed", "cancelled"])
async def test_nonterminal_or_failed_runs_never_queue_an_answer(
    db: AsyncSession, world: World, status: str
) -> None:
    world.run.status = status
    await db.flush()
    await RoutineDeliveryService(db).queue(world.run, answer="Not final")
    assert await delivery_repo.get(db, run_id=world.run.id, organization_id=world.org.id) is None


async def test_storage_refuses_cross_tenant_or_wrong_origin_admission(
    db: AsyncSession, world: World
) -> None:
    assert not await delivery_repo.create(
        db,
        run_id=world.run.id,
        organization_id=uuid4(),
        trigger_id=world.trigger.id,
        answer="Wrong tenant",
    )
    assert not await delivery_repo.create(
        db,
        run_id=world.run.id,
        organization_id=world.org.id,
        trigger_id=uuid4(),
        answer="Wrong responsibility",
    )
    assert await delivery_repo.get(db, run_id=world.run.id, organization_id=world.org.id) is None


@pytest.mark.parametrize(
    "answer_to,answer,expected", [("run_log", "Done", "run_log"), ("conversation", "", "no_answer")]
)
async def test_log_only_and_empty_answers_settle_without_a_chat_message(
    db: AsyncSession, world: World, answer_to: str, answer: str, expected: str
) -> None:
    world.trigger.answer_to = answer_to
    await db.flush()
    await RoutineDeliveryService(db).queue(world.run, answer=answer)
    await AgentTriggerService(db).deliver_resumed_answer(world.org.id, world.run.id)
    receipt = await delivery_repo.get(db, run_id=world.run.id, organization_id=world.org.id)
    assert receipt is not None and receipt.status == expected
    assert await messages(db, world) == []


async def test_a_failed_enqueue_cannot_commit_an_orphaned_handoff(
    db: AsyncSession, world: World
) -> None:
    with (
        pytest.raises(RuntimeError),
        patch(
            "app.services.routine_delivery.enqueue", side_effect=RuntimeError("queue unavailable")
        ),
    ):
        async with db.begin_nested():
            await RoutineDeliveryService(db).queue(world.run, answer="Keep the terminal result")
    assert await delivery_repo.get(db, run_id=world.run.id, organization_id=world.org.id) is None
    await RoutineDeliveryService(db).queue(world.run, answer="Retry registration")
    assert (
        await delivery_repo.get(db, run_id=world.run.id, organization_id=world.org.id) is not None
    )


@pytest.mark.parametrize("cascade_last", [False, True])
async def test_removing_the_owner_erases_the_extra_answer_copy(
    db: AsyncSession, world: World, cascade_last: bool
) -> None:
    if cascade_last:
        # Exercise the trigger order produced when the cascade is installed last.
        # This DDL is rolled back together with the test's rows.
        await db.execute(
            text(
                "ALTER TABLE conversations DROP CONSTRAINT conversations_user_id_fkey, "
                "ADD CONSTRAINT conversations_user_id_fkey "
                "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            )
        )
    await RoutineDeliveryService(db).queue(world.run, answer="Private canonical output")
    run_id, organization_id = world.run.id, world.org.id
    successor = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(successor)
    await db.flush()
    world.org.created_by_user_id = successor.id
    db.add(OrganizationMember(organization_id=world.org.id, user_id=successor.id, role="owner"))
    await db.flush()
    await db.delete(world.user)
    await db.flush()
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db.refresh(world.trigger)
    assert world.trigger.delivery_conversation_id is None
    assert world.trigger.created_by_user_id is None
    assert await delivery_repo.get(db, run_id=run_id, organization_id=organization_id) is None
    await AgentTriggerService(db).deliver_resumed_answer(organization_id, run_id)


async def test_extra_answer_copies_belong_in_the_owners_bounded_export(
    db: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings
    from app.core.exceptions import BadRequestError
    from app.services.personal_data import PersonalDataService

    await RoutineDeliveryService(db).queue(world.run, answer="My pending answer")
    export = await PersonalDataService(db).export(world.user.id, actor_user_id=world.user.id)
    assert len(export.routine_deliveries) == 1
    assert export.routine_deliveries[0].answer == "My pending answer"
    other = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(other)
    await db.flush()
    theirs = await PersonalDataService(db).export(other.id, actor_user_id=other.id)
    assert theirs.routine_deliveries == []
    monkeypatch.setattr(settings, "PERSONAL_DATA_EXPORT_MAX_CHARS", 10)
    with pytest.raises(BadRequestError):
        await PersonalDataService(db).export(world.user.id, actor_user_id=world.user.id)


async def test_observed_expiry_closes_blockers_even_while_the_routine_is_paused(
    db: AsyncSession, world: World
) -> None:
    from app.db.models.outcome import Outcome
    from app.services.notifications import NotificationService

    await NotificationService(db).routine_blocked(
        organization_id=world.org.id,
        owner_user_id=world.user.id,
        routine_id=world.trigger.id,
        routine_kind="trigger",
        reason="run",
        name="Report",
        detail="Its last attempt failed.",
        observed_at=world.run.started_at,
    )
    await RoutineDeliveryService(db).queue(world.run, answer="Result after approval")
    world.trigger.is_active = False
    world.trigger.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    await AgentTriggerService(db).deliver_resumed_answer(world.org.id, world.run.id)
    (case,) = list(await db.scalars(select(Outcome)))
    assert case.status == "resolved"
    assert await messages(db, world) == []
    assert world.trigger.last_delivery_status == "unavailable"


async def test_conversation_updates_require_current_private_access_and_a_console_session(
    db: AsyncSession, world: World
) -> None:
    from dataclasses import replace

    from app.core.permissions import AuthContext, OrgRoleName, Perm
    from app.schemas.change_event import ChangeEvent
    from app.services import change_feed

    ctx = AuthContext(user_id=world.user.id, organization_id=world.org.id, role=OrgRoleName.MEMBER)
    event = ChangeEvent(
        organization_id=world.org.id,
        resource="conversation",
        id=world.chat.id,
        action="updated",
        surface="run",
        actor_user_id=world.user.id,
        actor_name=None,
    )
    assert not ctx.has(Perm.RUNS_VIEW)
    assert await change_feed.visible(db, ctx, event)
    assert not await change_feed.visible(db, replace(ctx, api_key_id=uuid4()), event)
    assert not await change_feed.visible(
        db, replace(ctx, key_scopes=frozenset({Perm.AGENTS_RUN})), event
    )
    assert not await change_feed.visible(
        db, replace(ctx, user_id=uuid4(), role=OrgRoleName.OWNER), event
    )
    assert not await change_feed.visible(db, ctx, event.model_copy(update={"id": None}))
    assert not await change_feed.visible(db, replace(ctx, organization_id=uuid4()), event)


async def test_a_saved_answer_announces_its_conversation_only_after_commit(
    db: AsyncSession, world: World
) -> None:
    from unittest.mock import AsyncMock

    from app.core.background import drain, start_deferred

    await RoutineDeliveryService(db).queue(world.run, answer="Live result")
    with patch("app.services.change_feed.publish", new=AsyncMock()) as published:
        await AgentTriggerService(db).deliver_resumed_answer(world.org.id, world.run.id)
        published.assert_not_awaited()
        await db.commit()
        start_deferred(db)
        await drain(timeout=1)
        events = [call.args[0] for call in published.await_args_list]
        assert {(event.resource, event.id) for event in events} == {
            ("conversation", world.chat.id),
            ("trigger", world.agent.id),
        }
        await AgentTriggerService(db).deliver_resumed_answer(world.org.id, world.run.id)
        await db.commit()
        start_deferred(db)
        await drain(timeout=1)
    assert len(await messages(db, world)) == 1


@pytest.mark.parametrize("projection", ["quota", "no_member"])
async def test_table_quota_does_not_lose_a_routine_finding(
    db: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch, projection: str
) -> None:
    from app.core.config import settings
    from app.core.permissions import AuthContext
    from app.db.models.outcome import Outcome
    from app.db.models.task_board import TaskBoard
    from app.schemas.routine_notifications import RoutineFinding
    from app.schemas.virtual_table import TableCreate
    from app.services.virtual_tables import VirtualTableService

    ctx = AuthContext(user_id=world.user.id, organization_id=world.org.id, role="owner")
    await VirtualTableService(db).create_table(ctx, TableCreate(name="Existing data"))
    # Quota audits use a separate committed transaction, as in a later routine run.
    await db.commit()
    monkeypatch.setattr(settings, "TABLES_MAX_PER_ORGANIZATION", 1)
    from app.services.routine_delivery import RoutineFindingService

    if projection == "no_member":
        monkeypatch.setattr("app.services.access.member_context", AsyncMock(return_value=None))
    service = RoutineFindingService(db)
    chat_id = await service.publish(
        run=world.run,
        user_id=world.user.id,
        origin_id=world.trigger.id,
        origin_kind="trigger",
        item=RoutineFinding(
            key="mail:123", revision="v1", title="Review draft", content="Draft reply"
        ),
    )
    assert chat_id is not None
    assert await db.scalar(select(Message).where(Message.conversation_id == chat_id)) is not None
    assert (
        await db.scalar(select(Outcome).where(Outcome.source_conversation_id == chat_id))
        is not None
    )
    assert (
        await db.scalar(select(Notification).where(Notification.recipient_user_id == world.user.id))
        is not None
    )
    assert (
        await db.scalar(select(TaskBoard).where(TaskBoard.organization_id == world.org.id)) is None
    )
    await db.commit()


@pytest.mark.parametrize("status", ["ringing", "active"])
async def test_new_finding_revision_durably_ends_its_previous_telephone_call(
    db: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    from unittest.mock import AsyncMock

    from app.db.models.outcome import Outcome
    from app.schemas.routine_notifications import RoutineFinding
    from app.services.routine_delivery import RoutineFindingService
    from tests.integration import test_telephony as phone

    monkeypatch.setattr(phone, "seed_member", AsyncMock(return_value=(world.user, world.org)))
    ctx, _, _, _, endpoint = await phone.setup(db, monkeypatch)
    service = RoutineFindingService(db)
    finding = RoutineFinding(
        key="mail:123", revision="one", title="Review reply", content="Draft reply"
    )
    chat_id = await service.publish(
        run=world.run,
        user_id=world.user.id,
        origin_id=world.trigger.id,
        origin_kind="trigger",
        item=finding,
    )
    case = await db.scalar(select(Outcome).where(Outcome.source_conversation_id == chat_id))
    assert case is not None
    receipt = await phone.report(db, ctx, endpoint.id)
    row = await phone.repo.call(db, receipt.id)
    assert row is not None
    row.status, row.outcome_id, row.purpose = status, case.id, "important"
    await db.flush()
    assert (
        await service.publish(
            run=world.run,
            user_id=world.user.id,
            origin_id=world.trigger.id,
            origin_kind="trigger",
            item=finding.model_copy(update={"revision": "two"}),
        )
        == chat_id
    )
    await db.refresh(row)
    assert row.status == "ending"
    job = await db.scalar(
        select(BackgroundJob).where(BackgroundJob.dedupe_key == f"phone-end:{row.id}")
    )
    assert job is not None and job.kind == "end-phone" and job.organization_id == world.org.id


async def test_resumed_delivery_cannot_replace_a_newer_runs_delivery_status(db, world):
    world.trigger.last_run_id = None
    await RoutineDeliveryService(db).queue(world.run, answer="Result")
    await AgentTriggerService(db).deliver_resumed_answer(world.org.id, world.run.id)
    assert world.trigger.last_delivery_status == "not_completed"
    assert len(await messages(db, world)) == 1


async def test_routine_expiring_during_delivery_does_not_send_a_finished_notice(
    db, world, monkeypatch
):
    from app.services.notifications import NotificationService

    service = AgentTriggerService(db)
    await RoutineDeliveryService(db).queue(world.run, answer="Result")
    expire = AsyncMock(side_effect=[False, True])
    notice = AsyncMock()
    monkeypatch.setattr(service, "_expire_if_ended", expire)
    monkeypatch.setattr(NotificationService, "routine_finished", notice)
    await service.deliver_resumed_answer(world.org.id, world.run.id)
    assert expire.await_count == 2
    notice.assert_not_awaited()
    assert len(await messages(db, world)) == 1
