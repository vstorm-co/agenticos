"""The chat sidebar lists only the reader's currently accessible routine logs."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Perm, Scope
from app.db.models.agent_run import AgentRun
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import conversation_repo
from app.schemas.conversation import ConversationRead
from app.services.agent_trigger import AgentTriggerService
from app.services.conversation import ConversationService
from tests.integration.test_routine_sources import world

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def log_for(db: AsyncSession, trigger: AgentTrigger, name: str) -> UUID:
    trigger.name = name
    return await AgentTriggerService(db)._run_log(trigger, agent_name="Worker")


@pytest.mark.parametrize(
    "scope, visibility, owns_agent, granted, visible",
    [
        (Scope.ALL, Visibility.PRIVATE, False, False, True),
        (Scope.OWN, Visibility.PRIVATE, True, False, True),
        (Scope.OWN, Visibility.ORG, False, False, False),
        (Scope.SHARED, Visibility.ORG, False, False, True),
        (Scope.SHARED, Visibility.PRIVATE, False, False, False),
        (Scope.TEAM, Visibility.TEAM, False, False, True),
        (Scope.NONE, Visibility.PRIVATE, False, True, True),
        (Scope.NONE, Visibility.ORG, False, False, False),
    ],
)
async def test_log_visibility_matches_live_agent_scope_without_other_peoples_logs(
    db: AsyncSession,
    scope: Scope,
    visibility: Visibility,
    owns_agent: bool,
    granted: bool,
    visible: bool,
) -> None:
    ctx, trigger, _, _ = await world(db)
    own_log = await log_for(db, trigger, "Weekly report")
    other = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(other)
    await db.flush()
    from app.db.models.agent import Agent

    agent = await db.get(Agent, trigger.agent_id)
    assert agent is not None
    agent.owner_user_id = ctx.user_id if owns_agent else other.id
    agent.visibility = visibility.value
    other_trigger = AgentTrigger(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        created_by_user_id=other.id,
        prompt="Other person's report",
        interval_seconds=300,
        next_fire_at=datetime.now(UTC),
    )
    db.add(other_trigger)
    await db.flush()
    await log_for(db, other_trigger, "Another person's routine")
    foreign, foreign_trigger, _, _ = await world(db)
    await log_for(db, foreign_trigger, "Foreign routine")
    assert foreign.organization_id != ctx.organization_id
    access = conversation_repo.RoutineLogAccess(
        scope=scope, shared_agent_ids=frozenset({agent.id}) if granted else frozenset()
    )
    rows = await conversation_repo.get_conversations_by_user(
        db, organization_id=ctx.organization_id, user_id=ctx.user_id, routine_access=access
    )
    assert {row.id for row in rows} == ({own_log} if visible else set())
    assert await conversation_repo.count_conversations(
        db, organization_id=ctx.organization_id, user_id=ctx.user_id, routine_access=access
    ) == int(visible)


async def test_sidebar_log_is_openable_searchable_and_carries_running_state(
    db: AsyncSession,
) -> None:
    ctx, trigger, _, _ = await world(db)
    conversation_id = await log_for(db, trigger, "Weekly report")
    run = AgentRun(
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        agent_id=trigger.agent_id,
        conversation_id=conversation_id,
        status="running",
        started_at=datetime.now(UTC),
        surface="schedule",
        routine_origin_id=trigger.id,
    )
    db.add(run)
    await db.flush()
    await conversation_repo.create_message(
        db,
        conversation_id=conversation_id,
        role="assistant",
        content="Working",
        agent_id=trigger.agent_id,
        run_id=run.id,
    )
    service = ConversationService(db)
    rows, total = await service.list_conversations(
        ctx.user_id,
        organization_id=ctx.organization_id,
        reader=ctx,
        search="Weekly",
        agent_id=trigger.agent_id,
        hide_api=True,
    )
    assert total == 1 and [row.id for row in rows] == [conversation_id]
    read = ConversationRead.model_validate(rows[0])
    assert read.title == "Weekly report"
    assert run.id in read.running_run_ids
    assert read.unread
    opened = await service.get_conversation(
        conversation_id, organization_id=ctx.organization_id, user_id=ctx.subject_id, ctx=ctx
    )
    assert opened.id == conversation_id
    rows, total = await service.list_conversations(
        ctx.user_id, organization_id=ctx.organization_id, reader=ctx, skip=1, limit=1
    )
    assert rows == [] and total == 1


@pytest.mark.parametrize("reader", ["no_runs_scope", "model", "none", "wrong_person"])
async def test_log_listing_never_broadens_model_or_unproved_reader_access(
    db: AsyncSession, reader: str
) -> None:
    ctx, trigger, _, _ = await world(db)
    await log_for(db, trigger, "Private routine")
    supplied = ctx
    if reader == "no_runs_scope":
        supplied = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW}))
    elif reader == "wrong_person":
        supplied = replace(ctx, user_id=uuid4())
    rows, total = await ConversationService(db).list_conversations(
        ctx.user_id,
        organization_id=ctx.organization_id,
        reader=None if reader == "none" else supplied,
        for_model=reader == "model",
    )
    assert rows == [] and total == 0
