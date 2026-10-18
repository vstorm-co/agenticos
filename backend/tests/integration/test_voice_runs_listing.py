"""Activity shows a reconnected call as one call (#54, amendment 9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.voice_call import VoiceEndReason
from app.repositories import agent_run_repo, voice_call_repo
from app.repositories.agent_run import RunFilters

pytestmark = pytest.mark.anyio


async def _world(db):
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        name="Support",
        slug=f"support-{uuid.uuid4().hex[:8]}",
        draft_spec=AgentSpec(name="Support").model_dump(mode="json"),
        visibility=Visibility.PRIVATE.value,
    )
    db.add(agent)
    await db.flush()
    return org, agent, user


async def _run(db, org, agent, *, modality: str, at: datetime) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        status="completed",
        modality=modality,
        started_at=at,
    )
    db.add(run)
    await db.flush()
    return run


async def _call(db, org, agent, user, run, *, resume_of=None, at: datetime):
    return await voice_call_repo.create(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        run_id=run.id,
        user_id=user.id,
        conversation_id=None,
        embed_id=None,
        surface="web",
        provider="openai",
        model="gpt-realtime",
        transport="webrtc",
        secret_id=None,
        worker_id="host:1",
        resume_of=resume_of,
        resume_token_hash="0" * 64,
        started_at=at,
    )


async def test_a_reconnected_call_lists_once_and_filters_by_modality(db):
    org, agent, user = await _world(db)
    now = datetime.now(UTC)
    root_run = await _run(db, org, agent, modality="voice", at=now - timedelta(minutes=5))
    continuation_run = await _run(db, org, agent, modality="voice", at=now - timedelta(minutes=2))
    text_run = await _run(db, org, agent, modality="text", at=now - timedelta(minutes=1))
    first = await _call(db, org, agent, user, root_run, at=now - timedelta(minutes=5))
    await voice_call_repo.end(
        db,
        first.id,
        at=now - timedelta(minutes=3),
        reason=VoiceEndReason.DISCONNECTED,
        cost_usd=Decimal("0.05"),
        seconds=120,
        guardrail_hits=0,
    )
    second = await _call(
        db, org, agent, user, continuation_run, resume_of=first.id, at=now - timedelta(minutes=2)
    )
    await voice_call_repo.heartbeat(db, second.id, at=now, cost_usd=Decimal("0.01"), seconds=30)

    voice, voice_total = await agent_run_repo.list_runs(
        db, organization_id=org.id, filters=RunFilters(modality="voice", one_row_per_call=True)
    )
    text, _ = await agent_run_repo.list_runs(
        db, organization_id=org.id, filters=RunFilters(modality="text", one_row_per_call=True)
    )
    every, every_total = await agent_run_repo.list_runs(
        db, organization_id=org.id, filters=RunFilters()
    )
    chains = await voice_call_repo.chains_for_runs(db, [root_run.id], organization_id=org.id)

    assert [r.id for r in voice] == [root_run.id] and voice_total == 1
    assert [r.id for r in text] == [text_run.id]
    # The export reads every row: a continuation's cost is still money spent.
    assert continuation_run.id in {r.id for r in every} and every_total == 3
    assert chains[root_run.id].connections == 2 and chains[root_run.id].seconds == 150
    assert chains[root_run.id].cost_usd == Decimal("0.06")


async def test_with_one_row_per_call_filters_read_the_calls_first_run(db):
    """Documented behaviour: a continuation's own status neither surfaces nor hides the
    call - the call is listed, or not, on its first run's status."""
    org, agent, user = await _world(db)
    now = datetime.now(UTC)
    root_run = await _run(db, org, agent, modality="voice", at=now - timedelta(minutes=5))
    continuation_run = await _run(db, org, agent, modality="voice", at=now - timedelta(minutes=2))
    continuation_run.status = "failed"
    await db.flush()
    first = await _call(db, org, agent, user, root_run, at=now - timedelta(minutes=5))
    await _call(
        db, org, agent, user, continuation_run, resume_of=first.id, at=now - timedelta(minutes=2)
    )

    failed, failed_total = await agent_run_repo.list_runs(
        db, organization_id=org.id, filters=RunFilters(statuses=["failed"], one_row_per_call=True)
    )
    completed, _ = await agent_run_repo.list_runs(
        db,
        organization_id=org.id,
        filters=RunFilters(statuses=["completed"], one_row_per_call=True),
    )

    assert (failed, failed_total) == ([], 0)
    assert [r.id for r in completed] == [root_run.id]


async def test_deleting_an_agent_keeps_its_calls_minutes(db):
    """`voice_calls.agent_id` is SET NULL: a deleted agent gives no minutes back."""
    from sqlalchemy import delete

    from app.db.models.agent import Agent

    org, agent, user = await _world(db)
    now = datetime.now(UTC)
    run = await _run(db, org, agent, modality="voice", at=now - timedelta(minutes=5))
    call = await _call(db, org, agent, user, run, at=now - timedelta(minutes=5))
    call_id, org_id, agent_id = call.id, org.id, agent.id
    await voice_call_repo.heartbeat(
        db, call_id, at=now - timedelta(minutes=4), cost_usd=Decimal("0.02"), seconds=60
    )

    await db.execute(delete(Agent).where(Agent.id == agent_id))
    await db.flush()
    db.expire_all()

    row = await voice_call_repo.get(db, call_id, organization_id=org_id)
    assert row is not None and row.agent_id is None
    usage = await voice_call_repo.usage_by_agent(
        db, organization_id=org_id, start=now - timedelta(days=1), end=now + timedelta(days=1)
    )
    assert [(agent, seconds) for agent, _name, seconds, _calls in usage] == [(None, 60)]


async def test_a_page_of_calls_reads_its_chains_in_a_bounded_number_of_queries(db, engine):
    """Activity lists up to a hundred runs a page. A query pair per hop per call made
    that page about two hundred round trips (RR-q03)."""
    from sqlalchemy import event

    org, agent, user = await _world(db)
    now = datetime.now(UTC)
    roots = []
    for index in range(12):
        root_run = await _run(db, org, agent, modality="voice", at=now - timedelta(minutes=30))
        first = await _call(db, org, agent, user, root_run, at=now - timedelta(minutes=30))
        await voice_call_repo.heartbeat(db, first.id, at=now, cost_usd=Decimal("0.01"), seconds=10)
        previous = first
        # Every third call reconnected twice: chains of one and of three connections.
        for _ in range(2 if index % 3 == 0 else 0):
            hop_run = await _run(db, org, agent, modality="voice", at=now - timedelta(minutes=20))
            previous = await _call(db, org, agent, user, hop_run, resume_of=previous.id, at=now)
            await voice_call_repo.heartbeat(
                db, previous.id, at=now, cost_usd=Decimal("0.02"), seconds=20
            )
        roots.append((root_run.id, index % 3 == 0))
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        chains = await voice_call_repo.chains_for_runs(
            db, [run_id for run_id, _ in roots], organization_id=org.id
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert len(statements) <= 2
    for run_id, reconnected in roots:
        chain = chains[run_id]
        if reconnected:
            assert (chain.connections, chain.seconds, chain.cost_usd) == (3, 50, Decimal("0.05"))
        else:
            assert (chain.connections, chain.seconds, chain.cost_usd) == (1, 10, Decimal("0.01"))


async def test_a_chain_is_read_only_within_the_callers_organization(db):
    org, agent, user = await _world(db)
    now = datetime.now(UTC)
    run = await _run(db, org, agent, modality="voice", at=now)
    await _call(db, org, agent, user, run, at=now)
    other, _, _ = await _world(db)

    assert await voice_call_repo.chains_for_runs(db, [run.id], organization_id=other.id) == {}
    assert await voice_call_repo.chains_for_runs(db, [], organization_id=org.id) == {}
