"""Less travelled pipeline paths: vanished or foreign rows, finished sessions and deferred rounds."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.authoring import AuthoringRequest, AuthoringStatus, BatchStatus, HunkStatus
from app.db.models.dataset import DatasetCase
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.db.models.notification import Notification
from app.repositories import authoring_repo, improvement_repo, knowledge_gap_repo
from app.schemas.improvement import (
    ImprovementContinue,
    ImprovementFinish,
    ImprovementSelection,
    ImprovementStart,
)
from app.services.improvement_pipeline import ImprovementPipelineService, KnowledgePlan
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _rated, _setup
from tests.integration.test_eval_suites import _dataset, _owner
from tests.integration.test_improvement_continuation import _consent
from tests.integration.test_improvement_evidence import _serial_worker as _serial_worker
from tests.integration.test_improvement_knowledge import _world as _knowledge_world
from tests.integration.test_improvement_knowledge_steps import _job, _providers, _start
from tests.integration.test_improvement_knowledge_steps import _world as _steps_world
from tests.integration.test_improvement_pipeline import (
    _queued_advances,
    _ready_proposal,
    _started,
    _until_child,
)
from tests.integration.test_improvement_rounds import _round
from tests.integration.test_knowledge_gaps import _knowledge_base

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _candidate_batch(
    db: AsyncSession, ctx: AuthContext, agent: Agent, run: ImprovementRun
) -> UUID:
    batch = await authoring_repo.create_batch(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        request_id=None,
        source_started_at=run.created_at,
        expected_effect="A separately measured change",
        evidence_conversation_ids=[],
        improvement_run_id=run.id,
    )
    await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=batch.id,
        hunks=[
            {
                "kind": "spec_field",
                "origin": "improve",
                "path": "description",
                "op": "set",
                "base_value": None,
                "new_value": "Refund questions",
                "rationale": "Clarify purpose",
            }
        ],
    )
    return batch.id


def _vanishing[T](
    listing: Callable[..., Awaitable[list[T]]], run_id: Callable[[T], UUID]
) -> Callable[..., Awaitable[list[T]]]:
    """`listing`, with each listed session deleted before the caller reads it."""

    async def listed(db: AsyncSession, **kwargs: Any) -> list[T]:
        rows = await listing(db, **kwargs)
        for row in rows:
            await db.delete(await db.get(ImprovementRun, run_id(row)))
        await db.flush()
        return rows

    return listed


@pytest.mark.security
async def test_a_knowledge_step_owned_by_another_tenant_fails_the_session(
    db: AsyncSession,
) -> None:
    ctx, agent, _, dataset, _ = await _steps_world(db)
    other = await _owner(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        row = await db.get(ImprovementRun, read.id)
        assert row is not None
        job, _ = await _job(db, row)
        job.organization_id = other.organization_id
        await db.flush()
        service = ImprovementPipelineService(db)
        await service.advance(read.id, ctx.organization_id)
        failed = await service.read(ctx, agent.id, read.id)
    assert (failed.status, failed.stage) == ("failed", "classifying")
    assert failed.error == "Knowledge step not found"


async def test_a_classifier_still_making_progress_keeps_the_session_waiting(
    db: AsyncSession,
) -> None:
    ctx, agent, _, dataset, _ = await _steps_world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        row = await db.get(ImprovementRun, read.id)
        assert row is not None
        job, _ = await _job(db, row)
        job.status = "running"
        job.started_at = datetime.now(UTC)
        await db.flush()
        service = ImprovementPipelineService(db)
        await service.advance(read.id, ctx.organization_id)
        waiting = await service.read(ctx, agent.id, read.id)
    assert (waiting.status, waiting.stage, waiting.stop_reason) == ("running", "classifying", None)
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=read.id, number=1
    )
    assert iteration is not None and iteration.classify_job_id == job.id


async def test_the_agent_wide_preview_reads_recent_rated_runs_without_a_dataset(
    db: AsyncSession,
) -> None:
    ctx, agent, _, _ = await _started(db)
    late = await _rated(db, ctx, agent, comment="A later problem")
    preview = await ImprovementPipelineService(db).evidence(ctx, agent.id)
    assert late.id in {item.run_id for item in preview.items}
    assert len(preview.items) == 2


async def test_stopping_an_already_cancelled_session_changes_nothing(db: AsyncSession) -> None:
    ctx, agent, _, read = await _started(db)
    service = ImprovementPipelineService(db)
    cancelled = await service.cancel(ctx, agent.id, read.id)
    assert cancelled.status == "cancelled"
    again = await service.cancel(ctx, agent.id, read.id)
    assert again.status == "cancelled"
    assert len(again.timeline) == len(cancelled.timeline)


async def test_finishing_a_round_without_a_recorded_selection_accepts_only_pending_changes(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    batch_id = ready.iterations[0].batch_id
    assert batch_id is not None
    [dropped] = await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=batch_id,
        hunks=[
            {
                "kind": "spec_field",
                "origin": "improve",
                "path": "description",
                "op": "set",
                "base_value": None,
                "new_value": "Dropped before measuring",
                "rationale": "Removed by the change policy",
            }
        ],
    )
    dropped.status = HunkStatus.DISMISSED.value
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=ready.id, number=1
    )
    assert iteration is not None
    iteration.included_hunk_ids = None
    await db.flush()
    result = await ImprovementPipelineService(db).finish(
        ctx, agent.id, ready.id, ImprovementFinish(confirmed=True)
    )
    assert result.session.status == "accepted"
    assert dropped.status == HunkStatus.DISMISSED.value
    spec = AgentSpec.model_validate(agent.draft_spec)
    assert "30 days" in spec.instructions
    assert spec.description != "Dropped before measuring"


@pytest.mark.security
async def test_a_retried_proposal_stops_when_the_budget_no_longer_covers_it(
    db: AsyncSession,
) -> None:
    ctx, agent, _, read = await _started(db)
    service = ImprovementPipelineService(db)
    await _until_child(db, ctx, read.id)
    request_id = (await service.read(ctx, agent.id, read.id)).iterations[0].authoring_request_id
    assert request_id is not None
    request = await authoring_repo.get_request(db, request_id, organization_id=ctx.organization_id)
    assert request is not None
    await authoring_repo.update_request(
        db, request=request, values={"status": AuthoringStatus.FAILED.value}
    )
    await service.advance(read.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, read.id)).status == "failed"
    row = await db.get(ImprovementRun, read.id)
    assert row is not None
    row.budget_usd = Decimal("0.000001")
    await db.flush()
    requests = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    retried = await service.retry(ctx, agent.id, read.id)
    assert (retried.status, retried.stage, retried.stop_reason) == (
        "stopped",
        "proposing",
        "budget",
    )
    assert retried.iterations[0].authoring_request_id is None
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == requests


@pytest.mark.security
@pytest.mark.parametrize("operation", ["continuation", "selection", "select_round"])
async def test_a_round_whose_candidate_resolves_to_another_tenant_is_not_found(
    db: AsyncSession, operation: str
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    other = await _owner(db)
    batch_id = ready.iterations[0].batch_id
    assert batch_id is not None
    batch = await authoring_repo.get_batch(db, batch_id, organization_id=ctx.organization_id)
    assert batch is not None
    hunk_ids = [
        h.id
        for h in await authoring_repo.list_hunks(
            db, organization_id=ctx.organization_id, batch_id=batch_id
        )
    ]
    batch.organization_id = other.organization_id
    if operation == "continuation":
        row = await db.get(ImprovementRun, ready.id)
        assert row is not None
        row.status, row.stage, row.stop_reason = "failed", "evaluating", "eval"
    await db.flush()
    checks = await db.scalar(select(func.count()).select_from(EvalRun))
    service = ImprovementPipelineService(db)
    with pytest.raises(NotFoundError, match="no longer available"):
        if operation == "continuation":
            await service.estimate_continuation(
                ctx, agent.id, ready.id, ImprovementContinue(budget_usd=Decimal("5"))
            )
        elif operation == "selection":
            await service.estimate_selection(
                ctx, agent.id, ready.id, 1, ImprovementSelection(hunk_ids=hunk_ids)
            )
        else:
            await service.select_round(ctx, agent.id, ready.id, 1)
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == checks


async def test_a_deferred_candidate_continues_into_filtering_without_a_new_proposal(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    row.max_iterations = 3
    deferred = await improvement_repo.create_iteration(
        db, organization_id=ctx.organization_id, run_id=row.id, number=2
    )
    deferred.batch_id = await _candidate_batch(db, ctx, agent, row)
    await db.flush()
    service = ImprovementPipelineService(db)
    quote, consent = await _consent(service, ctx, agent, ready)
    assert (quote.mode, quote.number) == ("next_round", 2)
    requests = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    started = await service.continue_run(ctx, agent.id, ready.id, consent)
    assert (started.status, started.stage, started.iteration) == ("running", "proposing", 2)
    assert [item.id for item in started.iterations] == [ready.iterations[0].id, deferred.id]
    await service.advance(ready.id, ctx.organization_id)
    current = await service.read(ctx, agent.id, ready.id)
    assert current.stage == "filtering"
    assert current.iterations[1].batch_id == deferred.batch_id
    assert current.iterations[1].authoring_request_id is None
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == requests


async def test_a_regressed_round_moves_on_to_a_candidate_already_deferred_to_the_next(
    db: AsyncSession,
) -> None:
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=8)
    rows = list(
        await db.scalars(
            select(DatasetCase)
            .where(DatasetCase.dataset_id == dataset.id)
            .order_by(DatasetCase.position)
        )
    )
    for index, case in enumerate(rows):
        case.improvement_partition = "train" if index < 3 else "holdout"
    await db.flush()
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(100), max_iterations=3),
    )
    for _ in range(2):
        await service.advance(started.id, ctx.organization_id)
    row = await db.get(ImprovementRun, started.id)
    assert row is not None
    deferred = await improvement_repo.create_iteration(
        db, organization_id=ctx.organization_id, run_id=row.id, number=2
    )
    deferred.batch_id = await _candidate_batch(db, ctx, agent, row)
    await db.flush()
    await _round(db, ctx, agent, started.id, "ROUND_BAD")
    moved = await service.read(ctx, agent.id, started.id)
    assert moved.iterations[0].verdict == "regression"
    assert (moved.status, moved.stage, moved.iteration) == ("running", "proposing", 2)
    assert [item.id for item in moved.iterations] == [moved.iterations[0].id, deferred.id]
    requests = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    await service.advance(started.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, started.id)).stage == "filtering"
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == requests


@pytest.mark.parametrize("state", ["active", "waiting"])
async def test_the_sweep_skips_sessions_removed_after_they_were_listed(
    db: AsyncSession, state: str
) -> None:
    if state == "active":
        _, _, _, read = await _started(db)
    else:
        _, _, read = await _ready_proposal(db)
    queued = await _queued_advances(db, read.id)
    with (
        patch.object(
            improvement_repo,
            "list_active",
            new=_vanishing(improvement_repo.list_active, lambda row: row[0]),
        ),
        patch.object(
            improvement_repo,
            "list_deciding",
            new=_vanishing(improvement_repo.list_deciding, lambda row: row[0]),
        ),
    ):
        assert await ImprovementPipelineService(db).sweep() == 0
    assert await db.get(ImprovementRun, read.id) is None
    assert await _queued_advances(db, read.id) == queued


async def test_a_review_skips_a_session_removed_while_it_is_recorded(db: AsyncSession) -> None:
    ctx, _, ready = await _ready_proposal(db)
    check_id = ready.iterations[0].eval_run_ids[-1]
    with patch.object(
        improvement_repo,
        "runs_for_checks",
        new=_vanishing(improvement_repo.runs_for_checks, lambda run_id: run_id),
    ):
        await ImprovementPipelineService(db).recompute_after_review(ctx, [check_id])
    assert await db.get(ImprovementRun, ready.id) is None
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AppAdminAuditLog)
            .where(AppAdminAuditLog.action == "improvement.review_recomputed")
        )
        == 0
    )


async def test_a_replaced_candidate_rejects_the_waiting_session(db: AsyncSession) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    batch_id = ready.iterations[0].batch_id
    assert batch_id is not None
    batch = await authoring_repo.get_batch(db, batch_id, organization_id=ctx.organization_id)
    assert batch is not None
    await authoring_repo.close_batch(db, batch=batch, status=BatchStatus.SUPERSEDED)
    service = ImprovementPipelineService(db)
    await service.advance(ready.id, ctx.organization_id)
    rejected = await service.read(ctx, agent.id, ready.id)
    assert rejected.status == "rejected"
    assert rejected.timeline[-1].action == "improvement.rejected"


async def test_a_session_without_a_starting_person_stops_without_a_notice(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    check_id = ready.iterations[0].eval_run_ids[-1]
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    row.created_by_user_id = None
    await db.flush()
    notices = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.event_type == "improvement_finished")
    )
    await ImprovementPipelineService(db).recompute_after_review(ctx, [check_id])
    stopped = await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "permission")
    assert (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.event_type == "improvement_finished")
        )
        == notices
    )


async def test_review_without_access_marks_only_the_reviewed_round_of_a_cancelled_session(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    check_id = ready.iterations[0].eval_run_ids[-1]
    service = ImprovementPipelineService(db)
    assert (await service.cancel(ctx, agent.id, ready.id)).status == "cancelled"
    await improvement_repo.create_iteration(
        db, organization_id=ctx.organization_id, run_id=ready.id, number=2
    )
    with patch("app.services.improvement_pipeline.job_context", new=AsyncMock(return_value=None)):
        await service.recompute_after_review(ctx, [check_id])
    current = await service.read(ctx, agent.id, ready.id)
    assert (current.status, current.stop_reason) == ("cancelled", None)
    detail = current.iterations[0].verdict_detail
    assert current.iterations[0].verdict == "inconclusive"
    assert detail is not None and detail["reason"] == "review_access_unavailable"
    assert current.iterations[1].verdict is None


async def test_a_selected_change_that_no_longer_applies_is_refused_and_left_pending(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    batch_id = ready.iterations[0].batch_id
    assert batch_id is not None
    [stale] = await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=batch_id,
        hunks=[
            {
                "kind": "instructions",
                "origin": "verify",
                "old_text": "A sentence the instructions never contained.",
                "new_text": "Its replacement.",
            }
        ],
    )
    with pytest.raises(ConcurrentChangeError, match="no longer applies"):
        await ImprovementPipelineService(db).estimate_selection(
            ctx, agent.id, ready.id, 1, ImprovementSelection(hunk_ids=[stale.id])
        )
    assert stale.status == HunkStatus.PENDING.value


async def test_reselecting_a_round_after_a_person_opened_newer_suggestions_goes_stale(
    db: AsyncSession,
) -> None:
    ctx, agent, ready = await _ready_proposal(db)
    batch_id = ready.iterations[0].batch_id
    assert batch_id is not None
    exposed = await authoring_repo.get_batch(db, batch_id, organization_id=ctx.organization_id)
    assert exposed is not None
    await authoring_repo.close_batch(db, batch=exposed, status=BatchStatus.SUPERSEDED)
    person = await authoring_repo.create_batch(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        request_id=None,
        source_started_at=datetime.now(UTC),
        expected_effect="A person's own suggestions",
        evidence_conversation_ids=[],
    )
    stale = await ImprovementPipelineService(db).select_round(ctx, agent.id, ready.id, 1)
    assert (stale.status, stale.stop_reason) == ("stale", "superseded")
    assert stale.best_iteration_id == ready.best_iteration_id
    current = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert current is not None and current.id == person.id
    assert exposed.status == BatchStatus.SUPERSEDED.value


async def test_a_draft_for_a_base_the_round_does_not_search_is_refused(db: AsyncSession) -> None:
    ctx, agent, session, target = await _knowledge_world(db)
    topic = await knowledge_gap_repo.get_topic(
        db, target.topic_id, organization_id=ctx.organization_id
    )
    assert topic is not None
    topic.knowledge_base_id = (await _knowledge_base(db, ctx, "elsewhere")).id
    await db.flush()
    checks = await db.scalar(select(func.count()).select_from(EvalRun))
    with pytest.raises(BadRequestError, match="does not search this knowledge base"):
        await ImprovementPipelineService(db).estimate_knowledge(ctx, agent.id, session.id, target)
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == checks


async def test_a_knowledge_check_needs_the_sessions_pinned_test_questions(
    db: AsyncSession,
) -> None:
    ctx, agent, session, target = await _knowledge_world(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.dataset_version += 1
    await db.flush()
    checks = await db.scalar(select(func.count()).select_from(EvalRun))
    with pytest.raises(NotFoundError, match="test questions no longer exist"):
        await ImprovementPipelineService(db).estimate_knowledge(ctx, agent.id, session.id, target)
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == checks


async def test_a_knowledge_check_adds_the_draft_to_an_already_enabled_context_capability(
    db: AsyncSession,
) -> None:
    ctx, agent, session, target = await _knowledge_world(db, context=True)
    plan = await ImprovementPipelineService(db)._knowledge_plan(ctx, agent.id, session.id, target)
    assert isinstance(plan, KnowledgePlan)
    assert plan.quote.can_measure
    assert plan.candidate.capabilities == plan.base.capabilities
    assert [binding.id for binding in plan.candidate.capabilities].count("context") == 1
    assert plan.candidate.context_ids == [*plan.base.context_ids, target.topic_id]
