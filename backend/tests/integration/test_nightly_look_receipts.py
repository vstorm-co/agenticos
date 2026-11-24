"""A nightly look tracks its own calls and the requests it actually read (#2777)."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.system_agent_profile import DAILY_BRIEFING, MEMORY_MAINTENANCE
from app.db.models.user import User
from app.repositories import agent_run_repo, conversation_repo, member_repo
from app.services.proactive._nightly import NightlyLook, NightlyReading
from tests.integration.test_proactivity import _agent, _organization, _person, _turn

pytestmark = pytest.mark.anyio

_NOW = datetime.now(UTC)
_NIGHTLY = "app.services.proactive._nightly"


def _receipt(message: Message) -> tuple[uuid.UUID | None, str | None]:
    return message.nightly_read_by_user_id, message.nightly_read_content_hash


async def _background(
    db: AsyncSession,
    org: Organization,
    person: User,
    agent: Agent,
    at: datetime,
    *,
    role: str | None,
) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=person.id,
        surface=RunSurface.PROACTIVE.value,
        system_role=role,
        status=RunStatus.COMPLETED.value,
        started_at=at,
        ended_at=at,
        cost_usd=Decimal("0.01"),
    )
    db.add(run)
    await db.flush()
    return run


def _thinker(db: AsyncSession, org: Organization, person: User, agent: Agent) -> MagicMock:
    async def think(ctx: AuthContext, **options: object) -> NightlyReading:
        assert ctx.user_id == person.id and ctx.organization_id == org.id
        at = options["started_at"]
        assert isinstance(at, datetime)
        await _background(db, org, person, agent, at, role=DAILY_BRIEFING)
        return NightlyReading(starters=["Plan my day"])

    return MagicMock(
        starter_agent=AsyncMock(return_value=agent), think=AsyncMock(side_effect=think)
    )


async def _look_at(look: NightlyLook, org: Organization, person: User, at: datetime) -> int:
    with patch(f"{_NIGHTLY}.datetime") as clock:
        clock.now.return_value = at
        return await look.look(org.id, person.id)


async def _readable_prompt(
    db: AsyncSession,
) -> tuple[Organization, User, Agent, Message, AgentRun]:
    person = await _person(db)
    org = await _organization(db, person)
    agent = await _agent(db, org)
    chat = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=person.id)
    db.add(chat)
    await db.flush()
    run = await _turn(db, org, agent, person, input_tokens=40)
    message = Message(
        id=uuid.uuid4(),
        conversation_id=chat.id,
        run_id=run.id,
        role="user",
        content="Prepare the report",
        created_at=_NOW - timedelta(hours=1),
    )
    db.add(message)
    await db.flush()
    return org, person, agent, message, run


async def test_a_recent_watch_does_not_postpone_a_due_nightly_look(db: AsyncSession) -> None:
    person = await _person(db)
    org = await _organization(db, person)
    agent = await _agent(db, org)
    await _background(db, org, person, agent, _NOW - timedelta(hours=21), role=DAILY_BRIEFING)
    await _background(db, org, person, agent, _NOW - timedelta(minutes=5), role=None)

    assert await NightlyLook(db).due(org.id, person.id, now=_NOW)


async def test_settling_an_already_read_parked_turn_needs_no_extra_model_call(
    db: AsyncSession,
) -> None:
    person = await _person(db)
    org = await _organization(db, person)
    agent = await _agent(db, org)
    chat = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=person.id)
    db.add(chat)
    await db.flush()
    parked = await _turn(
        db,
        org,
        agent,
        person,
        status=RunStatus.AWAITING_APPROVAL,
        input_tokens=40,
        ended_at=_NOW - timedelta(minutes=10),
    )
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=chat.id,
            run_id=parked.id,
            role="user",
            content="Draft the weekly report",
            created_at=_NOW - timedelta(hours=1),
        )
    )
    await db.flush()
    look = NightlyLook(db)
    look.thinker = thinker = _thinker(db, org, person, agent)
    await _look_at(look, org, person, _NOW)
    assert thinker.think.await_count == 1

    parked.status = RunStatus.COMPLETED.value
    parked.ended_at = _NOW + timedelta(minutes=30)
    await db.flush()
    await _look_at(look, org, person, _NOW + timedelta(hours=21))

    assert thinker.think.await_count == 1


async def test_an_unread_deferred_prompt_survives_a_watch_between_looks(db: AsyncSession) -> None:
    person = await _person(db)
    org = await _organization(db, person)
    agent = await _agent(db, org)
    chat = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=person.id)
    db.add(chat)
    await db.flush()
    deferred = await _turn(db, org, agent, person, status=RunStatus.RUNNING, ended_at=None)
    message = Message(
        id=uuid.uuid4(),
        conversation_id=chat.id,
        run_id=deferred.id,
        role="user",
        content="Prepare the weekly report",
        created_at=_NOW - timedelta(hours=1),
    )
    db.add(message)
    await db.flush()
    look = NightlyLook(db)
    look.thinker = thinker = _thinker(db, org, person, agent)
    await _look_at(look, org, person, _NOW)
    assert thinker.think.await_count == 1
    assert _receipt(message) == (None, None)

    deferred.status = RunStatus.COMPLETED.value
    deferred.ended_at = _NOW + timedelta(hours=1)
    await _background(db, org, person, agent, _NOW + timedelta(hours=2), role=None)
    await db.flush()
    assert await look.due(org.id, person.id, now=_NOW + timedelta(hours=21))
    await _look_at(look, org, person, _NOW + timedelta(hours=21))
    assert thinker.think.await_count == 2
    assert "Prepare the weekly report" in thinker.think.await_args.kwargs["prompt"]
    await _look_at(look, org, person, _NOW + timedelta(hours=42))
    assert thinker.think.await_count == 2


@pytest.mark.security
async def test_the_look_clock_is_separate_from_personal_spending_and_other_scopes(
    db: AsyncSession,
) -> None:
    person = await _person(db)
    other = await _person(db)
    org = await _organization(db, person)
    elsewhere = await _organization(db, person)
    agent = await _agent(db, org)
    another_agent = await _agent(db, elsewhere)
    at = _NOW - timedelta(hours=21)
    await _background(db, org, person, agent, at, role=DAILY_BRIEFING)
    await _background(db, org, person, agent, _NOW, role=None)
    await _background(db, org, person, agent, _NOW, role=MEMORY_MAINTENANCE)
    await _background(db, org, other, agent, _NOW, role=DAILY_BRIEFING)
    await _background(db, elsewhere, person, another_agent, _NOW, role=DAILY_BRIEFING)
    web = await _background(db, org, person, agent, _NOW, role=DAILY_BRIEFING)
    web.surface = RunSurface.WEB.value
    await db.flush()

    assert (
        await agent_run_repo.last_nightly_run_at(db, organization_id=org.id, user_id=person.id)
        == at
    )
    assert await agent_run_repo.proactive_spend_since(
        db, organization_id=org.id, user_id=person.id, since=_NOW - timedelta(days=1)
    ) == Decimal("0.02")


async def test_a_legacy_unclassified_run_cannot_postpone_the_first_identified_look(
    db: AsyncSession,
) -> None:
    person = await _person(db)
    org = await _organization(db, person)
    agent = await _agent(db, org)
    await _background(db, org, person, agent, _NOW, role=None)
    assert await NightlyLook(db).due(org.id, person.id, now=_NOW)


@pytest.mark.security
async def test_read_receipts_do_not_mark_other_people_tenants_roles_or_refused_messages(
    db: AsyncSession,
) -> None:
    person = await _person(db)
    other = await _person(db)
    org = await _organization(db, person)
    elsewhere = await _organization(db, person)
    mine = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=person.id)
    theirs = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=other.id)
    outside = Conversation(id=uuid.uuid4(), organization_id=elsewhere.id, user_id=person.id)
    db.add_all([mine, theirs, outside])
    await db.flush()
    messages = [
        Message(id=uuid.uuid4(), conversation_id=mine.id, role="user", content="mine"),
        Message(id=uuid.uuid4(), conversation_id=theirs.id, role="user", content="theirs"),
        Message(id=uuid.uuid4(), conversation_id=outside.id, role="user", content="outside"),
        Message(id=uuid.uuid4(), conversation_id=mine.id, role="assistant", content="answer"),
        Message(
            id=uuid.uuid4(),
            conversation_id=mine.id,
            role="user",
            content="refused",
            guardrail_refused=True,
        ),
        Message(
            id=uuid.uuid4(),
            conversation_id=mine.id,
            role="user",
            content="shared",
            author_user_id=other.id,
        ),
    ]
    db.add_all(messages)
    await db.flush()
    hashes = {
        message.id: hashlib.sha256(message.content.encode()).hexdigest() for message in messages
    }
    await conversation_repo.mark_nightly_reads(
        db,
        organization_id=org.id,
        user_id=person.id,
        content_hashes=hashes,
    )
    await db.commit()
    for message in messages:
        await db.refresh(message)
    assert _receipt(messages[0]) == (person.id, hashes[messages[0].id])
    assert all(_receipt(message) == (None, None) for message in messages[1:])


async def test_a_failed_look_keeps_its_inputs_unread_for_the_next_due_attempt(
    db: AsyncSession,
) -> None:
    org, person, agent, message, _run = await _readable_prompt(db)
    look = NightlyLook(db)
    look.thinker = thinker = _thinker(db, org, person, agent)
    successful = thinker.think.side_effect

    async def fail_once(ctx: AuthContext, **options: object) -> NightlyReading | None:
        if thinker.think.await_count == 1:
            attempt = await _background(db, org, person, agent, _NOW, role=DAILY_BRIEFING)
            attempt.status = RunStatus.FAILED.value
            await db.flush()
            return None
        return await successful(ctx, **options)

    thinker.think.side_effect = fail_once
    await _look_at(look, org, person, _NOW)
    assert _receipt(message) == (None, None)
    assert not await look.due(org.id, person.id, now=_NOW + timedelta(hours=1))
    assert await look.due(org.id, person.id, now=_NOW + timedelta(hours=21))
    await _look_at(look, org, person, _NOW + timedelta(hours=21))
    assert thinker.think.await_count == 2
    assert _receipt(message) != (None, None)
    await _look_at(look, org, person, _NOW + timedelta(hours=42))
    assert thinker.think.await_count == 2


async def test_a_message_changed_during_the_model_call_remains_unread(db: AsyncSession) -> None:
    org, person, agent, message, _run = await _readable_prompt(db)
    original_hash = hashlib.sha256(message.content.encode()).hexdigest()
    look = NightlyLook(db)
    look.thinker = thinker = _thinker(db, org, person, agent)
    successful = thinker.think.side_effect

    async def edit_once(ctx: AuthContext, **options: object) -> NightlyReading:
        result = await successful(ctx, **options)
        if thinker.think.await_count == 1:
            message.content = "Prepare the revised report"
            await db.flush()
        return result

    thinker.think.side_effect = edit_once
    await _look_at(look, org, person, _NOW)
    assert _receipt(message) == (person.id, original_hash)
    await _look_at(look, org, person, _NOW + timedelta(hours=21))
    assert thinker.think.await_count == 2
    assert "Prepare the revised report" in thinker.think.await_args.kwargs["prompt"]
    await _look_at(look, org, person, _NOW + timedelta(hours=42))
    assert thinker.think.await_count == 2


async def test_a_read_receipt_survives_a_resumed_turn_absent_from_an_intervening_look(
    db: AsyncSession,
) -> None:
    org, person, agent, message, run = await _readable_prompt(db)
    look = NightlyLook(db)
    look.thinker = thinker = _thinker(db, org, person, agent)
    await _look_at(look, org, person, _NOW)
    receipt = _receipt(message)
    run.status = RunStatus.RUNNING.value
    run.ended_at = None
    newer = await _turn(db, org, agent, person, input_tokens=40)
    db.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=message.conversation_id,
            run_id=newer.id,
            role="user",
            content="A separate request",
            created_at=_NOW + timedelta(hours=1),
        )
    )
    await db.flush()
    await _look_at(look, org, person, _NOW + timedelta(hours=21))
    assert thinker.think.await_count == 2
    assert _receipt(message) == receipt
    run.status = RunStatus.COMPLETED.value
    run.ended_at = _NOW + timedelta(hours=22)
    await db.flush()
    await _look_at(look, org, person, _NOW + timedelta(hours=42))
    assert thinker.think.await_count == 2


@pytest.mark.security
async def test_a_changed_reader_does_not_inherit_the_previous_read_receipt(
    db: AsyncSession,
) -> None:
    org, person, agent, message, _run = await _readable_prompt(db)
    previous = await _person(db)
    message.nightly_read_by_user_id = previous.id
    message.nightly_read_content_hash = hashlib.sha256(message.content.encode()).hexdigest()
    await _background(db, org, person, agent, _NOW - timedelta(hours=21), role=DAILY_BRIEFING)
    member = await member_repo.get_active(db, organization_id=org.id, user_id=person.id)
    assert member is not None
    await member_repo.set_personal_starters(db, member, starters=["Plan my day"], at=_NOW)
    look = NightlyLook(db)
    look.thinker = thinker = _thinker(db, org, person, agent)

    await _look_at(look, org, person, _NOW)

    thinker.think.assert_awaited_once()
    assert message.nightly_read_by_user_id == person.id


async def test_pruning_background_runs_does_not_make_read_messages_new(db: AsyncSession) -> None:
    org, person, agent, message, _run = await _readable_prompt(db)
    look = NightlyLook(db)
    look.thinker = thinker = _thinker(db, org, person, agent)
    await _look_at(look, org, person, _NOW)
    receipt = _receipt(message)
    await db.execute(
        delete(AgentRun).where(
            AgentRun.organization_id == org.id,
            AgentRun.user_id == person.id,
            AgentRun.surface == RunSurface.PROACTIVE.value,
        )
    )
    await db.flush()
    assert await look.due(org.id, person.id, now=_NOW + timedelta(hours=21))

    await _look_at(look, org, person, _NOW + timedelta(hours=21))

    assert thinker.think.await_count == 1
    assert _receipt(message) == receipt
