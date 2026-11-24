"""Questions pause a real agent step and continue its original model conversation."""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import Connection, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.background import discard_deferred
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.resource_grant import ResourceGrant
from app.db.models.workflow_run import (
    DispatchOutbox,
    NodeAttempt,
    NodeRun,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import agent_run as agent_run_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.agent_registry import AgentRegistryService
from app.services.approvals import ApprovalService
from app.services.workflow_execution import WorkflowExecutionService, dispatcher
from app.services.workflow_execution.reconciler import WorkflowReconcilerService
from tests.integration.test_workflow_agent_node import _graph, _profile, _tenant
from tests.integration.workflow_run_support import (
    SeededRun,
    drive,
    seed_run,
    settle,
    start_attempt,
    tick,
)

pytestmark = pytest.mark.anyio

_QUESTIONS = [
    {
        "header": "Audience",
        "question": "Who will use it?",
        "options": [{"label": "Everyone"}, {"label": "My team"}],
    }
]
_ANSWER = [{"selected": ["My team"], "answer": "", "skipped": False}]


class _Planner:
    def __init__(self, *, rounds: int = 2) -> None:
        self.rounds = rounds
        self.calls = 0
        self.returns: list[list[object]] = []

    async def respond(self, messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        self.calls += 1
        results = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == "ask_user_question"
        ]
        self.returns.append(results)
        if len(results) < self.rounds:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "ask_user_question",
                        {"questions": _QUESTIONS},
                        tool_call_id=f"question-{len(results) + 1}",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("A completed plan for My team.")])


async def _seed(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, *, rounds: int = 2
) -> tuple[SeededRun, _Planner]:
    member = await _tenant(engine)
    profile = await _profile(engine, member[1])
    ctx = AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner")
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        registry = AgentRegistryService(db)
        agent = await registry.create(
            ctx,
            AgentSpec(
                name="Planner",
                instructions="Ask before making the plan.",
                model_profile_id=profile,
                capabilities=[CapabilityBindingSpec(id="ask_user")],
            ),
        )
        version = await registry.publish(ctx, agent.id)
        await db.commit()
    planner = _Planner(rounds=rounds)
    monkeypatch.setattr(
        "app.agents.model_resolver.build_model", lambda *_args: FunctionModel(planner.respond)
    )
    return await seed_run(
        engine, _graph(agent.id, version.id), member=member, run_input={"q": "Plan for my team"}
    ), planner


async def _answer(seeded: SeededRun, call: str, *, via_agent: bool = False) -> uuid.UUID:
    async with seeded.factory() as db:
        service = WorkflowExecutionService(db)
        [waiting] = await service.questions(seeded.ctx, seeded.run.id)
        assert waiting.questions[0].tool_call_id == call
        if via_agent:
            result = await service.answer_agent_questions(
                seeded.ctx, waiting.agent_run_id, {call: _ANSWER}
            )
        else:
            result = await service.answer_questions(
                seeded.ctx, seeded.run.id, waiting.node_run_id, {call: _ANSWER}
            )
        assert result.status == WorkflowRunStatus.WAITING_FOR_USER
        await db.commit()
        return waiting.agent_run_id


async def test_repeated_questions_keep_the_same_agent_and_all_previous_tool_results(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch)
    assert (await drive(seeded)).status == "waiting_for_user"
    child_id = await _answer(seeded, "question-1", via_agent=True)
    assert planner.calls == 1  # Answer acceptance did not run a model in the request.
    async with seeded.factory() as db:
        assert await WorkflowExecutionService(db).questions(seeded.ctx, seeded.run.id) == []
    assert (await drive(seeded)).status == "waiting_for_user"
    assert await _answer(seeded, "question-2") == child_id
    completed = await drive(seeded)
    assert completed.status == "succeeded"
    assert completed.output["text"] == "A completed plan for My team."
    assert planner.returns == [
        [],
        [{"Audience": ["My team"]}],
        [{"Audience": ["My team"]}, {"Audience": ["My team"]}],
    ]
    async with seeded.factory() as db:
        [child] = (await db.execute(select(AgentRun))).scalars()
        assert child.id == child_id
        assert child.status == RunStatus.COMPLETED.value


async def test_duplicate_answers_queue_once_and_stale_answers_cannot_answer_a_later_question(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch)
    await drive(seeded)
    async with seeded.factory() as db:
        service = WorkflowExecutionService(db)
        [waiting] = await service.questions(seeded.ctx, seeded.run.id)
        for _ in range(2):
            await service.answer_questions(
                seeded.ctx, seeded.run.id, waiting.node_run_id, {"question-1": _ANSWER}
            )
        live = (
            (
                await db.execute(
                    select(DispatchOutbox).where(
                        DispatchOutbox.node_run_id == waiting.node_run_id,
                        DispatchOutbox.status == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(live) == 1
        with pytest.raises(BadRequestError):
            await service.answer_questions(
                seeded.ctx,
                seeded.run.id,
                waiting.node_run_id,
                {"question-1": [{"selected": ["Everyone"]}]},
            )
        await db.commit()
    await drive(seeded)
    async with seeded.factory() as db:
        with pytest.raises(BadRequestError):
            await WorkflowExecutionService(db).answer_questions(
                seeded.ctx, seeded.run.id, waiting.node_run_id, {"question-1": _ANSWER}
            )
    assert planner.calls == 2


@pytest.mark.security
async def test_an_editor_cannot_answer_as_another_person_and_a_cross_tenant_run_is_hidden(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, _ = await _seed(engine, monkeypatch)
    await drive(seeded)
    async with seeded.factory() as db:
        service = WorkflowExecutionService(db)
        [waiting] = await service.questions(seeded.ctx, seeded.run.id)
        other = AuthContext(user_id=uuid.uuid4(), organization_id=seeded.org.id, role="owner")
        assert await service.questions(other, seeded.run.id) == []
        with pytest.raises(AuthorizationError):
            await service.answer_questions(
                other, seeded.run.id, waiting.node_run_id, {"question-1": _ANSWER}
            )
        from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError

        alien = AuthContext(user_id=seeded.principal.id, organization_id=uuid.uuid4(), role="owner")
        with pytest.raises(WorkflowRunNotFoundError):
            await service.questions(alien, seeded.run.id)


@pytest.mark.security
async def test_question_controls_follow_current_run_grants_without_a_role_gate(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError

    seeded, planner = await _seed(engine, monkeypatch, rounds=1)
    await drive(seeded)
    viewer = AuthContext(user_id=seeded.principal.id, organization_id=seeded.org.id, role="viewer")
    async with seeded.factory() as db:
        service = WorkflowExecutionService(db)
        [original] = await service.questions(seeded.ctx, seeded.run.id)
        grant = ResourceGrant(
            organization_id=seeded.org.id,
            subject_user_id=seeded.principal.id,
            resource_type="workflow",
            resource_id=seeded.run.workflow_id,
            level="read",
        )
        db.add(grant)
        await db.flush()
        assert await service.questions(viewer, seeded.run.id) == []
        with pytest.raises(WorkflowRunNotFoundError):
            await service.answer_questions(
                viewer, seeded.run.id, original.node_run_id, {"question-1": _ANSWER}
            )

        grant.level = "use"
        await db.flush()
        [restored] = await service.questions(viewer, seeded.run.id)
        assert restored.agent_run_id == original.agent_run_id
        await service.answer_questions(
            viewer, seeded.run.id, restored.node_run_id, {"question-1": _ANSWER}
        )
        await db.commit()
    assert planner.calls == 1


async def test_expiry_wakes_the_parent_without_running_the_model_again(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch)
    await drive(seeded)
    async with seeded.factory() as db:
        child = (await db.execute(select(AgentRun))).scalar_one()
        child.ended_at = datetime.now(UTC) - timedelta(hours=settings.QUESTION_EXPIRY_HOURS + 1)
        await db.commit()
    async with seeded.factory() as db:
        assert await ApprovalService(db).expire_unanswered() == 1
        await db.commit()
        # Simulate losing the best-effort wake in a process restart.
        discard_deferred(db)
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).wake_stale_approval_decisions() == 1
        await db.commit()
    assert (await drive(seeded)).status == "failed"
    assert planner.calls == 1


async def test_cancelling_a_question_wait_closes_the_child_and_blocks_late_answers(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch)
    await drive(seeded)
    async with seeded.factory() as db:
        service = WorkflowExecutionService(db)
        [waiting] = await service.questions(seeded.ctx, seeded.run.id)
        await service.cancel(seeded.ctx, seeded.run.id)
        await db.commit()
    async with seeded.factory() as db:
        child = await db.get(AgentRun, waiting.agent_run_id)
        assert child.status == "cancelled" and child.paused_state is None
        from app.services.workflow_execution.exceptions import WorkflowRunAlreadyTerminalError

        with pytest.raises(WorkflowRunAlreadyTerminalError):
            await WorkflowExecutionService(db).answer_questions(
                seeded.ctx, seeded.run.id, waiting.node_run_id, {"question-1": _ANSWER}
            )
    assert planner.calls == 1


async def test_expiry_before_the_workflow_records_its_wait_still_schedules_failure_collection(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch)
    async with seeded.factory() as db:
        entry = (await db.execute(select(NodeRun))).scalar_one()
    await tick(seeded, entry.id)
    async with seeded.factory() as db:
        node = (
            await db.execute(
                select(NodeRun).where(NodeRun.node_instance_id == seeded.graph.nodes[1].id)
            )
        ).scalar_one()
    begun = await start_attempt(seeded, node.id)
    outcome = await dispatcher.call_handler(begun)
    async with seeded.factory() as db:
        child = (await db.execute(select(AgentRun))).scalar_one()
        child.ended_at = datetime.now(UTC) - timedelta(hours=settings.QUESTION_EXPIRY_HOURS + 1)
        await db.flush()
        assert await ApprovalService(db).expire_unanswered() == 1
        await db.commit()
        discard_deferred(db)
    await settle(seeded, begun, outcome)
    assert (await drive(seeded)).status == "failed"
    assert planner.calls == 1


async def test_crash_after_the_child_parks_recovers_its_wait_and_books_only_new_cost(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch, rounds=1)
    async with seeded.factory() as db:
        entry = (await db.execute(select(NodeRun))).scalar_one()
    await tick(seeded, entry.id)
    async with seeded.factory() as db:
        node = (
            await db.execute(
                select(NodeRun).where(NodeRun.node_instance_id == seeded.graph.nodes[1].id)
            )
        ).scalar_one()
    begun = await start_attempt(seeded, node.id)
    await dispatcher.call_handler(begun)
    async with seeded.factory() as db:
        child = (await db.execute(select(AgentRun))).scalar_one()
        node = await db.get(NodeRun, node.id)
        assert node.waiting_agent_run_id == child.id  # Durable before settle.
        outbox = (
            await db.execute(select(DispatchOutbox).where(DispatchOutbox.node_run_id == node.id))
        ).scalar_one()
        outbox.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        # Simulate a late partial cost write before orphan recovery.
        attempt = await db.get(NodeAttempt, begun.attempt_id)
        child.cost_usd = Decimal("0.03")
        attempt.cost = Decimal("0.01")
        run = await db.get(WorkflowRun, seeded.run.id)
        run.spent_cost = Decimal("0.01")
        await db.commit()
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    async with seeded.factory() as db:
        run = await db.get(WorkflowRun, seeded.run.id)
        assert run.status == "waiting_for_user" and run.spent_cost == Decimal("0.03")
        attempt = await db.get(NodeAttempt, begun.attempt_id)
        assert attempt.cost == Decimal("0.03") and attempt.result["reason"] == "question"
    await _answer(seeded, "question-1")
    assert (await drive(seeded)).status == "succeeded"
    assert planner.calls == 2


async def test_saved_answers_are_reconciled_when_their_dispatch_row_is_lost(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch, rounds=1)
    await drive(seeded)
    await _answer(seeded, "question-1")
    async with seeded.factory() as db:
        pending = (
            await db.execute(
                select(DispatchOutbox).where(
                    DispatchOutbox.workflow_run_id == seeded.run.id,
                    DispatchOutbox.status == "pending",
                )
            )
        ).scalar_one()
        pending.status = "done"
        await db.commit()
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).wake_stale_approval_decisions() == 1
        await db.commit()
    assert (await drive(seeded)).status == "succeeded"
    assert planner.calls == 2


@pytest.mark.parametrize("late_park", [False, True])
async def test_cancelled_orphan_keeps_its_childs_known_cost_exactly_once(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, late_park: bool
) -> None:
    seeded, planner = await _seed(engine, monkeypatch, rounds=1)
    async with seeded.factory() as db:
        entry = (await db.execute(select(NodeRun))).scalar_one()
    await tick(seeded, entry.id)
    async with seeded.factory() as db:
        node = (
            await db.execute(
                select(NodeRun).where(NodeRun.node_instance_id == seeded.graph.nodes[1].id)
            )
        ).scalar_one()
    begun = await start_attempt(seeded, node.id)
    await dispatcher.call_handler(begun)
    async with seeded.factory() as db:
        child = (await db.execute(select(AgentRun))).scalar_one()
        checkpoint = child.paused_state
        child.cost_usd = Decimal("0.03")
        await db.commit()
    async with seeded.factory() as db:
        await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
        if late_park:
            child = await db.get(AgentRun, child.id)
            child.status = "awaiting_answer"
            child.paused_state = checkpoint
            child.ended_at = datetime.now(UTC)
        outbox = (
            await db.execute(select(DispatchOutbox).where(DispatchOutbox.node_run_id == node.id))
        ).scalar_one()
        outbox.updated_at = datetime.now(UTC) - timedelta(
            seconds=settings.WORKFLOW_DISPATCH_LEASE_SECONDS + 5
        )
        await db.commit()
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 0
        run = await db.get(WorkflowRun, seeded.run.id)
        attempt = await db.get(NodeAttempt, begun.attempt_id)
        node = await db.get(NodeRun, node.id)
        assert run.status == "cancelled" and run.spent_cost == Decimal("0.03")
        assert attempt.cost == Decimal("0.03") and attempt.agent_run_id == child.id
        assert node.waiting_agent_run_id is None
        child = await db.get(AgentRun, child.id)
        assert child.status == "cancelled" and child.paused_state is None
    assert planner.calls == 1


async def test_an_inherited_checkpoint_does_not_prove_an_interrupted_continuation_parked_again(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, planner = await _seed(engine, monkeypatch)
    await drive(seeded)
    await _answer(seeded, "question-1")
    async with seeded.factory() as db:
        node = (
            await db.execute(
                select(NodeRun).where(NodeRun.node_instance_id == seeded.graph.nodes[1].id)
            )
        ).scalar_one()
    begun = await start_attempt(seeded, node.id)
    async with seeded.factory() as db:
        attempt = await db.get(NodeAttempt, begun.attempt_id)
        child = await db.get(AgentRun, attempt.agent_run_id)
        assert child.ended_at < attempt.started_at
        outbox = (
            await db.execute(
                select(DispatchOutbox).where(
                    DispatchOutbox.node_run_id == node.id, DispatchOutbox.status == "claimed"
                )
            )
        ).scalar_one()
        outbox.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        for previous in (
            await db.execute(
                select(DispatchOutbox).where(
                    DispatchOutbox.node_run_id == node.id, DispatchOutbox.status == "done"
                )
            )
        ).scalars():
            previous.updated_at = datetime.now(UTC) - timedelta(
                seconds=settings.WORKFLOW_DISPATCH_LEASE_SECONDS + 5
            )
        await db.commit()
    async with seeded.factory() as db:
        assert await WorkflowReconcilerService(db).resolve_orphaned_attempts() == 1
        await db.commit()
        run = await db.get(WorkflowRun, seeded.run.id)
        assert run.status == "needs_attention"
        child = await db.get(AgentRun, child.id)
        assert child.status == "cancelled" and child.paused_state is None
    assert planner.calls == 1


async def test_accounting_for_one_child_excludes_a_different_child_on_the_same_step(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, _ = await _seed(engine, monkeypatch)
    await drive(seeded)
    async with seeded.factory() as db:
        [waiting] = await WorkflowExecutionService(db).questions(seeded.ctx, seeded.run.id)
        child = await db.get(AgentRun, waiting.agent_run_id)
        original = (
            await db.execute(select(NodeAttempt).where(NodeAttempt.agent_run_id == child.id))
        ).scalar_one()
        original.cost = Decimal("0.03")
        other = await agent_run_repo.create_run(
            db,
            organization_id=seeded.org.id,
            agent_id=child.agent_id,
            agent_version_id=child.agent_version_id,
            user_id=seeded.principal.id,
            conversation_id=child.conversation_id,
            surface="workflow",
            model_label=child.model_label,
            provider=child.provider,
            secret_id=None,
            started_at=datetime.now(UTC),
        )
        previous = await workflow_run_repo.create_attempt(
            db,
            organization_id=seeded.org.id,
            node_run_id=waiting.node_run_id,
            attempt_no=original.attempt_no + 1,
            idempotency_key="different-child",
            retry_guarantee=None,
            started_at=datetime.now(UTC),
            agent_run_id=other.id,
        )
        previous.cost = Decimal("1.00")
        previous.status = "failed"
        await db.flush()
        assert await workflow_run_repo.booked_agent_segments(
            db, node_run_id=waiting.node_run_id, agent_run_id=child.id
        ) == Decimal("0.03")


@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.security
async def test_a_question_answer_cannot_bypass_the_workflow_budget_or_deadline(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    seeded, planner = await _seed(engine, monkeypatch, rounds=1)
    await drive(seeded)
    await _answer(seeded, "question-1")
    async with seeded.factory() as db:
        run = await db.get(WorkflowRun, seeded.run.id)
        if expired:
            run.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            run.budget_limit = Decimal("0.000001")
            run.spent_cost = Decimal("0.000001")
        await db.commit()
    assert (await drive(seeded)).status == ("failed" if expired else "budget_exceeded")
    assert planner.calls == 1


async def test_downgrading_an_active_question_preserves_its_conversation_and_removes_new_state_keys(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.db.base import Base

    seeded, _ = await _seed(engine, monkeypatch, rounds=1)
    await drive(seeded)
    await _answer(seeded, "question-1")
    filename = Path(__file__).parents[2] / "alembic/versions/0298_workflow_question_wait.py"
    spec = importlib.util.spec_from_file_location("workflow_question_migration", filename)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def downgrade(connection: Connection) -> None:
        with Operations.context(
            MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
        ):
            migration.downgrade()

    # DDL and row changes are rolled back together, keeping the shared test
    # schema at head for the next test.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.run_sync(downgrade)
            status = await connection.scalar(
                text("SELECT status FROM workflow_runs WHERE id=:id"), {"id": seeded.run.id}
            )
            assert status == "needs_attention"
            child = (
                await connection.execute(text("SELECT paused_state FROM agent_runs"))
            ).scalar_one()
            assert "question_results" not in child
            assert child["messages"] and child["questions"] == ["question-1"]
            assert (
                await connection.scalar(
                    text(
                        "SELECT waiting_reason FROM node_runs WHERE waiting_agent_run_id IS NOT NULL"
                    )
                )
                is None
            )
        finally:
            await transaction.rollback()


async def test_a_failed_continuation_books_child_spend_even_when_the_handler_reports_no_cost(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows.contracts.results import Failed, WorkflowError

    seeded, _ = await _seed(engine, monkeypatch)
    await drive(seeded)
    child_id = await _answer(seeded, "question-1")
    async with seeded.factory() as db:
        node = (
            await db.execute(
                select(NodeRun).where(NodeRun.node_instance_id == seeded.graph.nodes[1].id)
            )
        ).scalar_one()
    begun = await start_attempt(seeded, node.id)
    async with seeded.factory() as db:
        child = await db.get(AgentRun, child_id)
        child.status = "failed"
        child.cost_usd = Decimal("0.05")
        child.cost_is_partial = True
        child.error = "The model request failed"
        await db.commit()
    failure = dispatcher.HandlerOutcome(
        result=Failed(error=WorkflowError(code="AGENT_RUN_FAILED", message="The agent run stopped"))
    )
    for _ in range(2):
        await settle(seeded, begun, failure)
    async with seeded.factory() as db:
        run = await db.get(WorkflowRun, seeded.run.id)
        attempt = await db.get(NodeAttempt, begun.attempt_id)
        assert run.status == "failed" and run.spent_cost == Decimal("0.05")
        assert attempt.cost == Decimal("0.05")
        assert run.cost_is_partial and attempt.cost_is_partial
