"""Private per-run chats and read-only shared histories preserve their boundaries."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.conversation import Conversation
from app.repositories import conversation_repo
from app.schemas.agent_trigger import TriggerCreate, TriggerUpdate
from app.services.agent_trigger import AgentTriggerService
from app.services.conversation import ConversationService
from tests.integration.test_routine_sources import world

pytestmark = pytest.mark.anyio


def test_new_routines_default_to_shared_history() -> None:
    assert TriggerCreate(prompt="Prepare a report", interval_seconds=86400).chat_mode == "shared"


async def test_each_activation_gets_a_private_conversation_without_changing_the_routine(
    db: AsyncSession,
) -> None:
    ctx, trigger, _, _ = await world(db)
    service = AgentTriggerService(db)
    first = await service._run_chat(trigger, agent_name="Worker")
    second = await service._run_chat(trigger, agent_name="Worker")
    assert first != second
    for identifier in (first, second):
        row = await db.get(Conversation, identifier)
        assert row is not None and row.user_id == ctx.user_id and row.origin is None
        assert row.organization_id == ctx.organization_id
        assert await ConversationService(db)._may_write(row, ctx.subject_id, turn=True, ctx=ctx)
    assert trigger.conversation_id is None
    assert trigger.prompt == "Check"


async def test_shared_history_is_read_only_and_the_creator_can_fork_an_answer(
    db: AsyncSession,
) -> None:
    ctx, trigger, _, _ = await world(db)
    trigger.chat_mode = "shared"
    identifier = await AgentTriggerService(db)._run_log(trigger, agent_name="Worker")
    service = ConversationService(db)
    history = await service.get_metadata(
        identifier, organization_id=ctx.organization_id, user_id=ctx.subject_id, ctx=ctx
    )
    assert history.origin == "routine" and history.user_id is None
    assert not await service._may_write(history, ctx.subject_id, turn=True, ctx=ctx)
    await conversation_repo.create_message(
        db, conversation_id=identifier, role="user", content="Prepare a report"
    )
    answer = await conversation_repo.create_message(
        db,
        conversation_id=identifier,
        role="assistant",
        content="The report",
        agent_id=trigger.agent_id,
    )
    copied = await service.fork(
        identifier,
        message_id=answer.id,
        organization_id=ctx.organization_id,
        user_id=ctx.subject_id,
        ctx=ctx,
    )
    assert copied.id != identifier and copied.user_id == ctx.user_id and copied.origin is None
    assert await service._may_write(copied, ctx.subject_id, turn=True, ctx=ctx)
    assert not await service._owns_routine_log(history, uuid4())
    with pytest.raises(NotFoundError):
        await service.get_conversation(
            identifier,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            for_write=True,
            turn=True,
            ctx=ctx,
        )


async def test_another_authorized_reader_cannot_fork_the_creators_history(db: AsyncSession) -> None:
    from app.core.permissions import AuthContext
    from app.db.models.organization import OrganizationMember
    from app.db.models.user import User
    from app.schemas.conversation import ConversationRead

    ctx, trigger, _, _ = await world(db)
    identifier = await AgentTriggerService(db)._run_log(trigger, agent_name="Worker")
    answer = await conversation_repo.create_message(
        db,
        conversation_id=identifier,
        role="assistant",
        content="Report",
        agent_id=trigger.agent_id,
    )
    other = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(other)
    await db.flush()
    db.add(OrganizationMember(organization_id=ctx.organization_id, user_id=other.id, role="owner"))
    await db.flush()
    reader = AuthContext(organization_id=ctx.organization_id, user_id=other.id, role="owner")
    service = ConversationService(db)
    own = await service.get_metadata(
        identifier, organization_id=ctx.organization_id, user_id=ctx.subject_id, ctx=ctx
    )
    assert ConversationRead.model_validate(own).can_fork_routine_log
    theirs = await service.get_metadata(
        identifier, organization_id=ctx.organization_id, user_id=other.id, ctx=reader
    )
    assert not ConversationRead.model_validate(theirs).can_fork_routine_log
    with pytest.raises(NotFoundError):
        await service.fork(
            identifier,
            message_id=answer.id,
            organization_id=ctx.organization_id,
            user_id=other.id,
            ctx=reader,
        )


@pytest.mark.parametrize("mode", ["per_run", "shared", "invalid"])
async def test_chat_mode_is_frozen_in_run_authority(db: AsyncSession, mode: str) -> None:
    from app.core.exceptions import AuthorizationError
    from app.db.models.agent_run import AgentRun
    from app.services.routine_authority import RoutineAuthority
    from tests.integration.test_routine_authority import _world

    world = await _world(db)
    run = AgentRun(
        routine_origin_id=world.trigger.id,
        user_id=world.user.id,
        routine_kind="trigger",
        routine_policy={"approved_sources": world.trigger.approved_sources, "chat_mode": mode},
    )
    if mode == "invalid":
        with pytest.raises(AuthorizationError):
            await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    else:
        authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
        assert authority is not None and authority.chat_mode == mode


async def test_a_private_run_chat_refuses_an_unattributed_routine(db: AsyncSession) -> None:
    from app.core.exceptions import AuthorizationError

    _, trigger, _, _ = await world(db)
    trigger.created_by_user_id = None
    with pytest.raises(AuthorizationError, match="creator"):
        await AgentTriggerService(db)._run_chat(trigger, agent_name="Worker")


async def test_a_shared_project_history_needs_project_access_and_stays_read_only(
    db: AsyncSession,
) -> None:
    from dataclasses import replace

    from app.core.permissions import Perm
    from app.db.models.project import Project

    ctx, trigger, _, _ = await world(db)
    project = Project(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="Private project",
        backend="state",
    )
    db.add(project)
    await db.flush()
    trigger.project_id = project.id
    identifier = await AgentTriggerService(db)._run_log(trigger, agent_name="Worker")
    service = ConversationService(db)
    history = await service.get_conversation(
        identifier, organization_id=ctx.organization_id, user_id=ctx.subject_id, ctx=ctx
    )
    assert not await service._may_write(history, ctx.subject_id, turn=True, ctx=ctx)
    limited = replace(ctx, key_scopes=frozenset({Perm.RUNS_VIEW, Perm.AGENTS_VIEW}))
    with pytest.raises(NotFoundError):
        await service.get_conversation(
            identifier, organization_id=ctx.organization_id, user_id=ctx.subject_id, ctx=limited
        )
    socket_history = await service.get_conversation(
        identifier, organization_id=ctx.organization_id, user_id=ctx.subject_id
    )
    assert socket_history.id == identifier


@pytest.mark.security
async def test_routine_history_spans_chats_without_other_routines_or_tenants(
    db: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    from app.db.models.agent_run import AgentRun
    from app.repositories import agent_run_repo
    from app.repositories.agent_run import RunFilters

    ctx, trigger, _, _ = await world(db)
    conversations = [
        await AgentTriggerService(db)._run_chat(trigger, agent_name="Worker") for _ in range(2)
    ]
    for index, conversation in enumerate(conversations):
        db.add(
            AgentRun(
                organization_id=ctx.organization_id,
                agent_id=trigger.agent_id,
                user_id=ctx.user_id,
                conversation_id=conversation,
                trigger_id=trigger.id if index == 0 else None,
                routine_kind="trigger",
                routine_origin_id=trigger.id,
                status="completed",
                started_at=datetime.now(UTC),
            )
        )
    db.add(
        AgentRun(
            organization_id=ctx.organization_id,
            agent_id=trigger.agent_id,
            user_id=ctx.user_id,
            routine_kind="watch",
            routine_origin_id=trigger.id,
            routine_policy={},
            status="completed",
            started_at=datetime.now(UTC),
        )
    )
    foreign, foreign_trigger, _, _ = await world(db)
    db.add(
        AgentRun(
            organization_id=foreign.organization_id,
            agent_id=foreign_trigger.agent_id,
            user_id=foreign.user_id,
            routine_kind="trigger",
            routine_origin_id=trigger.id,
            status="completed",
            started_at=datetime.now(UTC),
        )
    )
    await db.flush()
    rows, total = await agent_run_repo.list_runs(
        db, organization_id=ctx.organization_id, filters=RunFilters(trigger_id=trigger.id)
    )
    assert total == 2 and {row.conversation_id for row in rows} == set(conversations)
    page, count = await agent_run_repo.list_runs(
        db,
        organization_id=ctx.organization_id,
        filters=RunFilters(trigger_id=trigger.id),
        skip=1,
        limit=1,
    )
    assert count == 2 and len(page) == 1


@pytest.mark.parametrize("name", ["Renamed report", None])
async def test_renaming_shared_routine_updates_its_sidebar_history(
    db: AsyncSession, name: str | None
) -> None:
    ctx, trigger, spec, _ = await world(db)
    trigger.name = "Original report"
    trigger.chat_mode = "shared"
    service = AgentTriggerService(db)
    identifier = await service._run_log(trigger, agent_name=spec.name)
    await service.update(ctx, trigger.agent_id, trigger.id, TriggerUpdate(name=name))
    history = await conversation_repo.get_conversation_by_id(db, identifier, fresh=True)
    assert history is not None
    assert history.title == (name or f"{spec.name} - scheduled")


@pytest.mark.parametrize("invalid", ["missing", "organization", "origin", "project"])
async def test_routine_rename_cannot_relabel_an_unrelated_conversation(
    db: AsyncSession, invalid: str
) -> None:
    ctx, trigger, spec, _ = await world(db)
    trigger.name = "Original report"
    trigger.chat_mode = "shared"
    service = AgentTriggerService(db)
    identifier = await service._run_log(trigger, agent_name=spec.name)
    candidate = Conversation(
        id=identifier,
        organization_id=uuid4() if invalid == "organization" else ctx.organization_id,
        origin=None if invalid == "origin" else "routine",
        project_id=uuid4() if invalid == "project" else None,
        title="Unrelated history",
    )
    with patch(
        "app.repositories.conversation.get_conversation_by_id",
        new=AsyncMock(return_value=None if invalid == "missing" else candidate),
    ):
        await service.update(ctx, trigger.agent_id, trigger.id, TriggerUpdate(name="Renamed"))
    history = await conversation_repo.get_conversation_by_id(db, identifier, fresh=True)
    assert history is not None and history.title == "Original report"
