"""Call rows: what bounds a call nobody hung up (#54)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.voice_call import VoiceEndReason
from app.repositories import voice_call_repo

pytestmark = pytest.mark.anyio


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, founder: User) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


@pytest.fixture
async def voice_rows(db):
    """An organization, an agent, a run, the caller and the conversation the call is in."""
    user = await _user(db)
    organization = await _org(db, user)
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=user.id,
        name="Support",
        slug=f"support-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Support").model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user.id, organization_id=organization.id, title="Call"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=organization.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return organization, agent, run, user, conversation


@pytest.fixture
async def other_organization(db):
    return await _org(db, await _user(db))


async def _call(db, ctx_rows, *, started=None, resume_of=None, user_id=None):
    org, agent, run, user, conversation = ctx_rows
    return await voice_call_repo.create(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        run_id=run.id,
        user_id=user_id or user.id,
        conversation_id=conversation.id,
        embed_id=None,
        surface="web",
        provider="openai",
        model="gpt-realtime",
        transport="webrtc",
        secret_id=None,
        worker_id="host:1",
        resume_of=resume_of,
        resume_token_hash="0" * 64,
        started_at=started or datetime.now(UTC),
    )


async def test_minutes_count_ended_calls_and_open_calls_up_to_their_heartbeat(db, voice_rows):
    now = datetime.now(UTC)
    ended = await _call(db, voice_rows, started=now - timedelta(minutes=10))
    await voice_call_repo.end(
        db,
        ended.id,
        at=now - timedelta(minutes=7),
        reason=VoiceEndReason.USER,
        cost_usd=Decimal("0.10"),
        seconds=180,
        guardrail_hits=0,
    )
    live = await _call(db, voice_rows, started=now - timedelta(minutes=2))
    await voice_call_repo.heartbeat(
        db, live.id, at=now - timedelta(minutes=1), cost_usd=Decimal("0.02"), seconds=60
    )

    used = await voice_call_repo.seconds_since(
        db, organization_id=voice_rows[0].id, since=now - timedelta(days=1)
    )

    assert used == 180 + 60


async def test_an_open_call_with_a_fresh_heartbeat_counts_against_the_concurrency_cap(
    db, voice_rows
):
    now = datetime.now(UTC)
    call = await _call(db, voice_rows)
    await voice_call_repo.heartbeat(db, call.id, at=now, cost_usd=Decimal(0), seconds=0)

    assert (
        await voice_call_repo.count_open_for_user(
            db, user_id=voice_rows[3].id, fresh_since=now - timedelta(seconds=45)
        )
        == 1
    )


async def test_the_reaper_query_finds_stale_and_ended_but_not_hung_up_calls(db, voice_rows):
    now = datetime.now(UTC)
    stale = await _call(db, voice_rows)
    await voice_call_repo.heartbeat(
        db, stale.id, at=now - timedelta(minutes=5), cost_usd=Decimal(0), seconds=0
    )
    hung = await _call(db, voice_rows)
    await voice_call_repo.end(
        db,
        hung.id,
        at=now,
        reason=VoiceEndReason.USER,
        cost_usd=Decimal(0),
        seconds=1,
        guardrail_hits=0,
    )
    await voice_call_repo.mark_hung_up(db, hung.id, at=now)
    fresh = await _call(db, voice_rows)
    await voice_call_repo.heartbeat(db, fresh.id, at=now, cost_usd=Decimal(0), seconds=0)

    found = {
        row.id
        for row in await voice_call_repo.list_unhung(db, stale_before=now - timedelta(seconds=45))
    }

    assert found == {stale.id}


async def test_a_chain_sums_every_connection(db, voice_rows):
    first = await _call(db, voice_rows)
    await voice_call_repo.end(
        db,
        first.id,
        at=datetime.now(UTC),
        reason=VoiceEndReason.DISCONNECTED,
        cost_usd=Decimal("0.05"),
        seconds=120,
        guardrail_hits=0,
    )
    second = await _call(db, voice_rows, resume_of=first.id)
    await voice_call_repo.heartbeat(
        db, second.id, at=datetime.now(UTC), cost_usd=Decimal("0.01"), seconds=30
    )

    assert await voice_call_repo.chain_seconds(db, second.id) == 150


async def test_a_second_end_keeps_the_first_reason_and_the_larger_figures(db, voice_rows):
    """A reconnect ends a half-open connection early; its owner's later teardown
    must not lose the final cost and seconds (Task 17's takeover)."""
    call = await _call(db, voice_rows)
    now = datetime.now(UTC)
    await voice_call_repo.end(
        db,
        call.id,
        at=now,
        reason=VoiceEndReason.DISCONNECTED,
        cost_usd=Decimal("0.10"),
        seconds=60,
        guardrail_hits=0,
    )
    await voice_call_repo.end(
        db,
        call.id,
        at=now + timedelta(seconds=20),
        reason=VoiceEndReason.USER,
        cost_usd=Decimal("0.14"),
        seconds=80,
        guardrail_hits=1,
    )
    await db.refresh(call)
    assert (call.end_reason, call.cost_usd, call.seconds, call.guardrail_hits) == (
        "disconnected",
        Decimal("0.14"),
        80,
        1,
    )
    assert call.ended_at == now


async def test_a_second_hang_up_keeps_the_first_stamp(db, voice_rows):
    """A reconnect from another worker hangs the connection up at its close; the
    holding worker's later teardown must not move the resume window's start."""
    call = await _call(db, voice_rows)
    now = datetime.now(UTC)
    await voice_call_repo.mark_hung_up(db, call.id, at=now)
    await voice_call_repo.mark_hung_up(db, call.id, at=now + timedelta(seconds=20))

    await db.refresh(call)
    assert call.hung_up_at == now


async def test_an_unknown_end_reason_is_refused(db, voice_rows):
    call = await _call(db, voice_rows)
    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE voice_calls SET end_reason = 'bored' WHERE id = :id"), {"id": call.id}
        )


async def test_a_run_row_is_text_unless_said_otherwise(db, voice_rows):
    assert voice_rows[2].modality == "text"


async def test_another_organizations_call_is_not_found(db, voice_rows, other_organization):
    call = await _call(db, voice_rows)
    assert await voice_call_repo.get(db, call.id, organization_id=other_organization.id) is None


@pytest.mark.security
async def test_an_agent_in_another_organization_cannot_be_called(
    db, voice_rows, other_organization
):
    """The starter maps this refusal to `forbidden`: no call reaches another tenant's agent."""
    from app.core.exceptions import NotFoundError
    from app.core.permissions import AuthContext, OrgRoleName, Perm
    from app.services.agent_registry import AgentRegistryService

    _, agent, _, user, _ = voice_rows
    ctx = AuthContext(
        user_id=user.id, organization_id=other_organization.id, role=OrgRoleName.OWNER
    )
    with pytest.raises(NotFoundError):
        await AgentRegistryService(db).get(ctx, agent.id, perm=Perm.AGENTS_RUN)


async def test_every_column_a_lookup_or_a_parent_delete_filters_on_leads_an_index(db):
    """The embed's open-call count runs under its advisory lock on every visitor's
    start, Activity walks `resume_of`, and each `ON DELETE SET NULL` parent looks its
    rows up by the column - none of them may scan the table (RR-q04)."""
    from sqlalchemy import inspect

    indexes = await db.run_sync(lambda sync: inspect(sync.connection()).get_indexes("voice_calls"))
    leading = {index["column_names"][0] for index in indexes}

    assert {
        "organization_id",
        "agent_id",
        "run_id",
        "user_id",
        "conversation_id",
        "embed_id",
        "secret_id",
        "resume_of",
    } <= leading


async def test_a_call_running_across_the_month_boundary_counts_its_part_after_it(db, voice_rows):
    """A call started before `since` and still going after it spends the new month's
    minutes for its part after `since`, and none of the old month's."""
    now = datetime.now(UTC)
    since = now - timedelta(minutes=5)
    across = await _call(db, voice_rows, started=since - timedelta(minutes=10))
    await voice_call_repo.heartbeat(db, across.id, at=now, cost_usd=Decimal(0), seconds=900)
    before = await _call(db, voice_rows, started=since - timedelta(minutes=20))
    await voice_call_repo.end(
        db,
        before.id,
        at=since - timedelta(minutes=15),
        reason=VoiceEndReason.USER,
        cost_usd=Decimal(0),
        seconds=300,
        guardrail_hits=0,
    )

    used = await voice_call_repo.seconds_since(db, organization_id=voice_rows[0].id, since=since)

    assert used == 300


async def test_a_chain_at_its_bound_has_no_seconds_so_it_cannot_be_resumed_again(db, voice_rows):
    """Past `_CHAIN_DEPTH` connections the older ones would drop out of the sum and
    hand their time back; such a chain is reported as `None`, not as a smaller sum."""
    from app.repositories.voice_call import _CHAIN_DEPTH

    previous = None
    for _ in range(_CHAIN_DEPTH - 1):
        previous = await _call(db, voice_rows, resume_of=None if previous is None else previous.id)
        await voice_call_repo.heartbeat(
            db, previous.id, at=datetime.now(UTC), cost_usd=Decimal(0), seconds=10
        )
    assert previous is not None
    assert await voice_call_repo.chain_seconds(db, previous.id) == 10 * (_CHAIN_DEPTH - 1)

    last = await _call(db, voice_rows, resume_of=previous.id)

    assert await voice_call_repo.chain_seconds(db, last.id) is None


async def test_a_connection_that_is_gone_has_no_seconds(db):
    assert await voice_call_repo.chain_seconds(db, uuid.uuid4()) == 0
