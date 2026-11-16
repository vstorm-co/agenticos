"""A delegated topic outlives its source turn, asked of real PostgreSQL rows."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import ModelMessage
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation
from app.db.models.conversation_task import ConversationTask, ConversationTurnClaim
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run as run_repo
from app.repositories import conversation as conversation_repo
from app.repositories import conversation_task as task_repo
from app.schemas.conversation_task import ConversationTaskRead, StartConversationTask
from app.schemas.local_target import LocalTarget
from app.services import conversation_turns
from app.services.agent_runner import AgentRunnerService, RunStream
from app.services.conversation_tasks import ConversationTaskService
from app.worker.jobs import RUN_CONVERSATION_TASK, ConversationTaskJob
from app.worker.tasks import conversation_tasks as worker

pytestmark = pytest.mark.anyio


@dataclass
class Seed:
    ctx: AuthContext
    source: AgentRun
    topic: Conversation
    agent: Agent


async def seed(db: AsyncSession) -> Seed:
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Acme", slug=f"acme-{uuid4().hex}", created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(id=uuid4(), organization_id=org.id, user_id=user.id, role="owner"))
    agent = Agent(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        slug=f"assistant-{uuid4().hex}",
        name="Assistant",
        status="published",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={
            "name": "Assistant",
            "model_profile_id": str(uuid4()),
            "capabilities": [{"id": "background_tasks"}],
        },
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    topic = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=user.id, title="Release planning"
    )
    source = await run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=user.id,
        conversation_id=topic.id,
        surface="web",
        model_label="test-model",
        provider="test",
        started_at=datetime.now(UTC),
    )
    await conversation_repo.create_message(
        db,
        conversation_id=topic.id,
        role="user",
        content="Work in the source conversation",
        run_id=source.id,
        author_user_id=user.id,
    )
    return Seed(
        AuthContext(user_id=user.id, organization_id=org.id, role="owner"), source, topic, agent
    )


async def start(
    db: AsyncSession, example: Seed, *, call: str = "delegate-1"
) -> ConversationTaskRead:
    return await ConversationTaskService(db).start(
        example.ctx,
        source_run_id=example.source.id,
        tool_call_id=call,
        request=StartConversationTask(
            title="Export bug", prompt="Investigate the unrelated export bug in a fresh topic."
        ),
    )


async def test_fresh_topic_is_atomic_idempotent_bounded_and_keeps_its_source(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    first = await start(db, example)
    again = await start(db, example)
    assert again.id == first.id
    assert first.conversation_id != example.topic.id
    topic = await db.get(Conversation, first.conversation_id)
    assert (
        topic is not None and topic.user_id == example.ctx.user_id and topic.title == "Export bug"
    )
    brief = await conversation_repo.get_messages_by_conversation(db, first.conversation_id)
    assert (
        len(brief) == 1 and brief[0].role == "assistant" and brief[0].agent_id == example.agent.id
    )
    assert "Investigate the unrelated export bug" in brief[0].content
    assert str(example.topic.id) in brief[0].content
    stored = await task_repo.get(db, first.id, organization_id=example.ctx.organization_id)
    assert stored is not None
    job = await db.get(BackgroundJob, stored.job_id)
    assert job is not None and job.max_attempts == 1 and job.kind == RUN_CONVERSATION_TASK.kind
    for i in range(2, 5):
        await start(db, example, call=f"delegate-{i}")
    with pytest.raises(AlreadyExistsError, match="Four tasks"):
        await start(db, example, call="delegate-5")
    shown = await ConversationTaskService(db).list_for_member(
        example.ctx, conversation_id=example.topic.id
    )
    assert len(shown) == 4
    assert not {"local_target", "job_id", "prompt"}.intersection(first.model_dump())
    task = await task_repo.get(db, first.id, organization_id=example.ctx.organization_id, lock=True)
    assert task is not None and "ConversationTask" in repr(task)


@pytest.mark.security
async def test_other_tenants_and_other_members_cannot_read_or_stop_a_task(db: AsyncSession) -> None:
    a, b = await seed(db), await seed(db)
    task = await start(db, a)
    for ctx in [
        b.ctx,
        AuthContext(user_id=b.ctx.user_id, organization_id=a.ctx.organization_id, role="owner"),
    ]:
        with pytest.raises(NotFoundError):
            await ConversationTaskService(db).get(ctx, task.id)
        with pytest.raises(NotFoundError):
            await ConversationTaskService(db).stop(ctx, task.id)
        assert await ConversationTaskService(db).list_for_member(ctx) == []
    assert await task_repo.get(db, task.id, organization_id=b.ctx.organization_id) is None
    assert await task_repo.for_run(db, a.source.id, organization_id=b.ctx.organization_id) is None
    with pytest.raises(NotFoundError):
        await ConversationTaskService(db).start(
            b.ctx,
            source_run_id=a.source.id,
            tool_call_id="attack",
            request=StartConversationTask(title="No", prompt="No"),
        )


@pytest.mark.parametrize(
    "field,value",
    [("surface", "api"), ("is_test", True), ("parent_run_id", "self"), ("agent_version_id", None)],
)
async def test_unattended_test_and_nested_sources_cannot_start_more_work(
    db: AsyncSession, field: str, value: object
) -> None:
    example = await seed(db)
    setattr(example.source, field, example.source.id if value == "self" else value)
    await db.flush()
    with pytest.raises((BadRequestError, NotFoundError)):
        await start(db, example)
    assert (
        await task_repo.active_count(
            db, organization_id=example.ctx.organization_id, user_id=example.ctx.subject_id
        )
        == 0
    )


async def test_only_current_or_pinned_agents_and_exact_local_devices_are_accepted(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    service = ConversationTaskService(db)
    with pytest.raises(AuthorizationError, match="not configured"):
        await service.start(
            example.ctx,
            source_run_id=example.source.id,
            tool_call_id="other",
            request=StartConversationTask(title="Other", prompt="Other", agent_id=uuid4()),
        )
    with pytest.raises(BadRequestError, match="specific computer"):
        await service.start(
            example.ctx,
            source_run_id=example.source.id,
            tool_call_id="local",
            request=StartConversationTask(title="Local", prompt="Local"),
            local=LocalTarget(folder="/approved", mode="full_access", coding_agent="codex"),
        )
    local = LocalTarget(
        folder="/approved",
        mode="full_access",
        coding_agent="codex",
        device_id=uuid4(),
        coding_model="fast",
        coding_effort="low",
    )
    task = await service.start(
        example.ctx,
        source_run_id=example.source.id,
        tool_call_id="local",
        request=StartConversationTask(title="Local", prompt="Local"),
        local=local,
    )
    stored = await service.get(example.ctx, task.id)
    assert stored.local_target == local.model_dump(mode="json")


async def test_turn_admission_is_shared_for_people_and_exclusive_for_result_delivery(
    engine: AsyncEngine, db: AsyncSession
) -> None:
    example = await seed(db)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def claim(background: bool) -> UUID | None:
        async with factory() as connection, connection.begin():
            return await task_repo.claim_turn(connection, example.topic.id, background=background)

    a, b = await asyncio.gather(claim(False), claim(False))
    assert a is not None and b is not None and a != b
    assert await claim(True) is None
    await task_repo.release_turn(db, a)
    await task_repo.release_turn(db, b)
    await db.commit()
    c, d = await asyncio.gather(claim(True), claim(True))
    assert (c is None) != (d is None)
    winner = c or d
    assert winner is not None
    assert await claim(False) is None
    assert await task_repo.renew_turn(db, winner)
    await db.execute(
        update(ConversationTurnClaim)
        .where(ConversationTurnClaim.id == winner)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()
    assert not await task_repo.renew_turn(db, winner)
    await db.commit()
    assert await claim(True) is not None
    assert (
        "ConversationTurnClaim" in repr(await db.get(ConversationTurnClaim, winner))
        or await db.get(ConversationTurnClaim, winner) is None
    )


async def test_parks_and_interrupted_attempts_are_not_replayed_and_notify_once(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    task = await start(db, example)
    row = await ConversationTaskService(db).get(example.ctx, task.id)
    run = await run_repo.create_run(
        db,
        organization_id=example.ctx.organization_id,
        agent_id=example.agent.id,
        agent_version_id=example.source.agent_version_id,
        user_id=example.ctx.user_id,
        conversation_id=task.conversation_id,
        surface="web",
        model_label="test",
        provider="test",
        started_at=datetime.now(UTC),
    )
    row.run_id = run.id
    row.status = "running"
    run.status = "awaiting_approval"
    await db.flush()
    service = ConversationTaskService(db)
    await service.settle(run)
    assert row.status == "awaiting_approval"
    assert await task_repo.pending_returns(db) == []
    run.status = "completed"
    example.source.status = "completed"
    await db.flush()
    assert len(await task_repo.unsettled_runs(db)) == 1
    await service.settle(run)
    await service.settle(run)
    jobs = list(
        (
            await db.scalars(
                select(BackgroundJob).where(BackgroundJob.kind == "return-conversation-task")
            )
        ).all()
    )
    assert len(jobs) == 1
    assert (await task_repo.pending_returns(db))[0].id == row.id
    another = await start(db, example, call="crashed")
    await service.interrupted(
        another.id, organization_id=example.ctx.organization_id, returning=False
    )
    interrupted = await service.get(example.ctx, another.id)
    assert interrupted.status == "interrupted" and "not restarted" in interrupted.outcome
    row.return_run_id = run.id
    await db.flush()
    # The unique run link cannot be claimed by two tasks.
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            interrupted.return_run_id = run.id
            await db.flush()


async def test_worker_keeps_source_free_and_delivers_the_result_once_with_fresh_history(
    engine: AsyncEngine, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = await seed(db)
    example.source.status = "completed"
    task = await start(db, example)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def context() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    monkeypatch.setattr(worker, "get_worker_db_context", context)
    monkeypatch.setattr(conversation_turns, "get_db_context", context)
    started, finish = asyncio.Event(), asyncio.Event()
    results: list[str] = []

    async def execute(
        self: AgentRunnerService,
        ctx: AuthContext,
        agent_id: UUID,
        prompt: str,
        *,
        said: str,
        surface: RunSurface,
        conversation_id: UUID,
        version_id: UUID,
        local: LocalTarget | None,
        message_history: Sequence[ModelMessage],
        acts_for_sender: bool,
        parks_questions: bool,
        on_run_open: Callable[[AgentRun], Awaitable[None]],
        stream: RunStream,
        conversation_task_id: UUID,
        result_only: bool,
        model_profile_id: UUID | None,
        thread_root_message_id: UUID | None,
        check_model_request: Callable[[AsyncSession], Awaitable[None]] | None,
    ) -> tuple[str, AgentRun]:
        assert said == "" and parks_questions and local is None
        run = await run_repo.create_run(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            agent_version_id=version_id,
            user_id=ctx.user_id,
            conversation_id=conversation_id,
            surface=surface.value,
            model_label="controlled-test-model",
            provider="test",
            started_at=datetime.now(UTC),
        )
        await on_run_open(run)
        await self.db.commit()
        if check_model_request is not None:
            await check_model_request(self.db)
        if result_only:
            assert ctx.fired_as_creator == "event" and not acts_for_sender
            assert "while the task works" in str(message_history)
            assert "untrusted" in prompt and "Evidence from the task" in prompt
            results.append(prompt)
        else:
            assert message_history == [] and acts_for_sender
            started.set()
            await finish.wait()
        answer = "Summary of the completed task" if result_only else "Evidence from the task"
        await conversation_repo.create_message(
            self.db,
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            agent_id=agent_id,
            run_id=run.id,
            thread_root_message_id=thread_root_message_id,
        )
        run.status = "completed"
        run.cost_usd = Decimal("0.01")
        await self.db.flush()
        await ConversationTaskService(self.db).settle(run)
        await self.db.commit()
        return answer, run

    monkeypatch.setattr(AgentRunnerService, "execute", execute)
    payload = ConversationTaskJob(task_id=task.id, organization_id=example.ctx.organization_id)
    async with asyncio.TaskGroup() as group:
        group.create_task(worker.run_task(payload))
        await asyncio.wait_for(started.wait(), 3)
        async with conversation_turns.claim(example.topic.id, background=False) as admitted:
            assert admitted
            async with context() as foreground:
                await conversation_repo.create_message(
                    foreground,
                    conversation_id=example.topic.id,
                    role="user",
                    content="Another question while the task works",
                    author_user_id=example.ctx.user_id,
                )
        finish.set()
    await worker.run_task(payload)
    await worker.return_task(payload)
    await worker.return_task(payload)
    assert len(results) == 1
    async with context() as check:
        stored = await task_repo.get(check, task.id, organization_id=example.ctx.organization_id)
        assert (
            stored is not None and stored.status == "completed" and stored.delivery == "delivered"
        )
        assert stored.run_id is not None and stored.return_run_id is not None
        child = await check.get(AgentRun, stored.run_id)
        parent = await check.get(AgentRun, stored.return_run_id)
        assert (
            child is not None
            and parent is not None
            and child.cost_usd == parent.cost_usd == Decimal("0.01")
        )


async def test_stop_withdraws_the_queued_attempt_and_never_restarts_completed_work(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    task = await start(db, example)
    service = ConversationTaskService(db)
    stopped = await service.stop(example.ctx, task.id)
    assert stopped.status == "cancelled"
    row = await service.get(example.ctx, task.id)
    job = await db.get(BackgroundJob, row.job_id)
    assert job is not None and job.status == "cancelled"
    again = await service.stop(example.ctx, task.id)
    assert again.status == "cancelled"
    row.delivery = "delivered"
    await service.queue_return(row)
    await service.interrupted(row.id, organization_id=example.ctx.organization_id, returning=False)
    assert row.status == "cancelled"
    await service.interrupted(uuid4(), organization_id=example.ctx.organization_id, returning=False)
    await service.settle(example.source)


async def test_a_reused_tool_call_cannot_silently_change_the_task(db: AsyncSession) -> None:
    example = await seed(db)
    await start(db, example)
    with pytest.raises(AlreadyExistsError, match="different task"):
        await ConversationTaskService(db).start(
            example.ctx,
            source_run_id=example.source.id,
            tool_call_id="delegate-1",
            request=StartConversationTask(title="Changed", prompt="Different external actions"),
        )


async def test_a_child_or_return_turn_cannot_delegate_again(db: AsyncSession) -> None:
    example = await seed(db)
    task = await start(db, example)
    row = await ConversationTaskService(db).get(example.ctx, task.id)
    row.run_id = example.source.id
    await db.flush()
    with pytest.raises(BadRequestError, match="cannot start another"):
        await start(db, example, call="recursive")


async def test_a_person_removed_from_the_organization_cannot_continue_a_queued_task(
    db: AsyncSession,
) -> None:
    from sqlalchemy import delete

    example = await seed(db)
    task = await start(db, example)
    service = ConversationTaskService(db)
    row = await service.get(example.ctx, task.id)
    await db.execute(
        delete(OrganizationMember).where(
            OrganizationMember.organization_id == example.ctx.organization_id
        )
    )
    with pytest.raises(AuthorizationError, match="no longer run"):
        await service.authority(row)


async def test_interrupted_and_parked_result_deliveries_keep_their_true_state(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    task = await start(db, example)
    service = ConversationTaskService(db)
    row = await service.get(example.ctx, task.id)
    row.return_run_id = example.source.id
    row.delivery = "running"
    example.source.status = "awaiting_answer"
    await db.flush()
    await service.settle(example.source)
    assert row.delivery == "running"
    await service.interrupted(row.id, organization_id=row.organization_id, returning=True)
    assert row.delivery == "interrupted"
    example.source.status = "completed"
    await db.flush()
    await service.settle(example.source)
    assert row.delivery == "interrupted"
    await service.interrupted(row.id, organization_id=row.organization_id, returning=True)
    assert row.delivery == "interrupted"


async def test_failed_runs_and_late_writers_do_not_overwrite_a_known_interruption(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    task = await start(db, example)
    service = ConversationTaskService(db)
    row = await service.get(example.ctx, task.id)
    row.run_id = example.source.id
    row.status = "running"
    example.source.status = "budget_exceeded"
    await db.flush()
    await service.settle(example.source)
    assert row.status == "failed"
    row.status = "interrupted"
    example.source.status = "completed"
    await db.flush()
    await service.settle(example.source)
    assert row.status == "interrupted"


async def test_the_background_delegate_runs_its_pin_and_not_its_new_default(
    db: AsyncSession,
) -> None:
    example = await seed(db)
    agent = Agent(
        id=uuid4(),
        organization_id=example.ctx.organization_id,
        owner_user_id=example.ctx.user_id,
        slug=f"delegate-{uuid4().hex}",
        name="Researcher",
        status="published",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    pinned = AgentVersion(
        id=uuid4(),
        agent_id=agent.id,
        organization_id=example.ctx.organization_id,
        version=1,
        spec={"name": "Researcher", "model_profile_id": str(uuid4())},
    )
    latest = AgentVersion(
        id=uuid4(),
        agent_id=agent.id,
        organization_id=example.ctx.organization_id,
        version=2,
        spec={"name": "Changed", "model_profile_id": str(uuid4())},
    )
    db.add_all([pinned, latest])
    await db.flush()
    agent.current_version_id = latest.id
    source = await db.get(AgentVersion, example.source.agent_version_id)
    assert source is not None
    source.spec = {
        **source.spec,
        "subagents": [{"agent_id": str(agent.id), "agent_version_id": str(pinned.id)}],
    }
    await db.flush()
    task = await ConversationTaskService(db).start(
        example.ctx,
        source_run_id=example.source.id,
        tool_call_id="pinned",
        request=StartConversationTask(title="Research", prompt="Research", agent_id=agent.id),
    )
    row = await task_repo.get(db, task.id, organization_id=example.ctx.organization_id)
    assert row is not None and row.version_id == pinned.id and row.version_id != latest.id


async def test_a_project_task_retains_the_project_and_disappears_after_access_is_removed(
    db: AsyncSession,
) -> None:
    from app.db.models.project import Project

    example = await seed(db)
    project = Project(
        id=uuid4(),
        organization_id=example.ctx.organization_id,
        owner_user_id=None,
        name="Shared work",
        visibility="org",
        backend="state",
    )
    db.add(project)
    await db.flush()
    example.topic.project_id = project.id
    await db.flush()
    task = await start(db, example)
    child = await db.get(Conversation, task.conversation_id)
    assert child is not None and child.project_id == project.id
    await db.execute(
        update(OrganizationMember)
        .where(OrganizationMember.organization_id == example.ctx.organization_id)
        .values(role="member")
    )
    ctx = AuthContext(
        user_id=example.ctx.user_id, organization_id=example.ctx.organization_id, role="member"
    )
    service = ConversationTaskService(db)
    assert len(await service.list_for_member(ctx)) == 1
    project.visibility = "private"
    await db.flush()
    assert await service.list_for_member(ctx) == []
    row = await task_repo.get(db, task.id, organization_id=ctx.organization_id)
    assert row is not None
    with pytest.raises((NotFoundError, AuthorizationError)):
        await service.authority(row)


@pytest.mark.parametrize(
    "status", ["running", "awaiting_approval", "missing", "finished_while_stopping"]
)
async def test_stopping_running_or_parked_work_preserves_its_latest_state(
    db: AsyncSession, status: str
) -> None:
    from unittest.mock import AsyncMock, patch

    example = await seed(db)
    task = await start(db, example)
    service = ConversationTaskService(db)
    row = await service.get(example.ctx, task.id)
    row.run_id = example.source.id
    row.job_id = None
    row.status = "running"
    example.source.status = (
        "awaiting_approval"
        if status in {"awaiting_approval", "finished_while_stopping"}
        else "running"
    )
    await db.flush()

    async def cancel(*_args) -> None:
        if status == "finished_while_stopping":
            row.status = "completed"
            await db.flush()

    with patch.object(
        AgentRunnerService, "cancel_parked", new=AsyncMock(side_effect=cancel)
    ) as cancel_parked:
        if status == "missing":
            with patch.object(run_repo, "get_run", new=AsyncMock(return_value=None)):
                stopped = await service.stop(example.ctx, task.id)
        else:
            stopped = await service.stop(example.ctx, task.id)
        assert stopped.status == (
            "completed" if status == "finished_while_stopping" else "cancelled"
        )
        assert cancel_parked.await_count == (
            1 if status in {"awaiting_approval", "finished_while_stopping"} else 0
        )


def test_turn_claim_reports_the_conversation_it_belongs_to() -> None:
    topic_id = uuid4()
    claim = ConversationTurnClaim(
        id=uuid4(), conversation_id=topic_id, background=True, expires_at=datetime.now(UTC)
    )
    assert str(topic_id) in repr(claim)


@pytest.mark.parametrize(
    "status",
    [
        "completed",
        "failed",
        "cancelled",
        "budget_exceeded",
        "guardrail_blocked",
        "loop_stopped",
        "awaiting_approval",
        "awaiting_answer",
    ],
)
async def test_only_a_successful_result_turn_is_marked_delivered(
    db: AsyncSession, status: str
) -> None:
    example = await seed(db)
    task = await start(db, example)
    service = ConversationTaskService(db)
    row = await service.get(example.ctx, task.id)
    row.return_run_id = example.source.id
    row.status = "completed"
    row.delivery = "running"
    example.source.status = status
    await db.flush()
    await service.settle(example.source)
    assert row.delivery == (
        "delivered"
        if status == "completed"
        else "running"
        if status in {"awaiting_approval", "awaiting_answer"}
        else "interrupted"
    )


async def test_reconciliation_indexes_skip_archived_task_history(db: AsyncSession) -> None:
    example = await seed(db)
    first = await start(db, example)
    row = await ConversationTaskService(db).get(example.ctx, first.id)
    records = [
        {
            "id": uuid4(),
            "organization_id": row.organization_id,
            "user_id": row.user_id,
            "source_conversation_id": row.source_conversation_id,
            "conversation_id": row.conversation_id,
            "source_run_id": row.source_run_id,
            "source_agent_id": row.source_agent_id,
            "source_version_id": row.source_version_id,
            "agent_id": row.agent_id,
            "version_id": row.version_id,
            "tool_call_id": f"history-{i}",
            "title": "Archived",
            "prompt": "Completed",
            "status": "completed",
            "delivery": "delivered",
        }
        for i in range(1000)
    ]
    await db.execute(insert(ConversationTask), records)
    row.status = "completed"
    example.source.status = "completed"
    await db.flush()
    await db.execute(text("ANALYZE conversation_tasks"))
    plan = await db.scalar(
        text(
            "EXPLAIN (FORMAT JSON) SELECT id FROM conversation_tasks WHERE delivery = 'pending' AND status IN ('completed', 'failed', 'cancelled', 'interrupted') ORDER BY created_at LIMIT 100"
        )
    )
    assert "conversation_tasks_pending_return_idx" in str(plan)
    assert [task.id for task in await task_repo.pending_returns(db)] == [row.id]
    row.status = "running"
    row.run_id = example.source.id
    await db.flush()
    await db.execute(text("ANALYZE conversation_tasks"))
    plan = await db.scalar(
        text(
            "EXPLAIN (FORMAT JSON) SELECT run_id FROM conversation_tasks WHERE status IN ('running', 'awaiting_approval', 'awaiting_answer') LIMIT 100"
        )
    )
    assert "conversation_tasks_unsettled_idx" in str(plan)
    assert [task.id for task, _run in await task_repo.unsettled_runs(db)] == [row.id]
