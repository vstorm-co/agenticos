"""Refusals and recovery keep a waiting improvement from spending or writing unexpectedly."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import Perm
from app.db.models.authoring import AuthoringRequest
from app.db.models.improvement import ImprovementRun
from app.db.models.organization import Organization
from app.repositories import improvement_repo
from app.schemas.improvement import ImprovementContinue, ImprovementDiscard, ImprovementFinish
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_continuation import _consent
from tests.integration.test_improvement_evidence import _serial_worker as _serial_worker
from tests.integration.test_improvement_pipeline import _ready_proposal, _started

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@pytest.mark.security
async def test_progress_without_run_access_excludes_errors_but_retains_the_session(
    db: AsyncSession,
) -> None:
    ctx, agent, _, session = await _started(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.error = "Private provider details"
    await db.flush()
    limited = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW}))
    listed = await ImprovementPipelineService(db).list_for_agent(limited, agent.id)
    assert [item.id for item in listed] == [session.id]
    assert listed[0].error is None
    assert not listed[0].knowledge_eval_run_ids


@pytest.mark.security
async def test_an_editor_cannot_stop_or_discard_someone_elses_session(db: AsyncSession) -> None:
    ctx, agent, _, session = await _started(db)
    other = replace(
        ctx,
        user_id=uuid4(),
        key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.AGENTS_EDIT, Perm.RUNS_VIEW}),
    )
    service = ImprovementPipelineService(db)
    with pytest.raises(AuthorizationError, match="creator"):
        await service.cancel(other, agent.id, session.id)
    with pytest.raises(AuthorizationError, match="creator"):
        await service.discard(other, agent.id, session.id, ImprovementDiscard(confirmed=True))
    assert (await service.read(ctx, agent.id, session.id)).status == "queued"


async def test_running_work_cannot_be_finished_continued_or_discarded(db: AsyncSession) -> None:
    ctx, agent, _, session = await _started(db)
    service = ImprovementPipelineService(db)
    with pytest.raises(BadRequestError, match="checked round"):
        await service.finish(ctx, agent.id, session.id, ImprovementFinish(confirmed=True))
    with pytest.raises(BadRequestError, match="cannot be continued"):
        await service.estimate_continuation(
            ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal("5"))
        )
    with pytest.raises(BadRequestError, match="Stop"):
        await service.discard(ctx, agent.id, session.id, ImprovementDiscard(confirmed=True))
    with pytest.raises(BadRequestError, match="finishes"):
        await service.select_round(ctx, agent.id, session.id, 1)


@pytest.mark.parametrize("failure", ["no_selection", "replaced", "edited", "active_check"])
async def test_finishing_refuses_unmeasured_or_unavailable_changes(
    db: AsyncSession, failure: str
) -> None:
    ctx, agent, session = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    before = dict(agent.draft_spec)
    if failure == "no_selection":
        row.best_iteration_id = None
    elif failure == "edited":
        iteration = await improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=session.id, number=1
        )
        assert iteration is not None
        iteration.candidate_spec_hash = "0" * 64
    await db.flush()
    if failure == "replaced":
        with (
            patch(
                "app.services.improvement_pipeline.authoring_repo.get_open_batch",
                AsyncMock(return_value=None),
            ),
            pytest.raises(ConcurrentChangeError, match="replaced"),
        ):
            await service.finish(ctx, agent.id, session.id, ImprovementFinish(confirmed=True))
    elif failure == "active_check":
        with (
            patch(
                "app.services.improvement_pipeline.improvement_repo.has_active_check",
                AsyncMock(return_value=True),
            ),
            pytest.raises(ConcurrentChangeError, match="finish"),
        ):
            await service.finish(ctx, agent.id, session.id, ImprovementFinish(confirmed=True))
    else:
        error = BadRequestError if failure == "no_selection" else ConcurrentChangeError
        with pytest.raises(error):
            await service.finish(ctx, agent.id, session.id, ImprovementFinish(confirmed=True))
    assert agent.draft_spec == before
    assert row.status == "ready"


@pytest.mark.parametrize("operation", ["finish", "continue", "discard"])
async def test_a_resource_removed_before_its_write_lock_is_not_found(
    db: AsyncSession, operation: str
) -> None:
    ctx, agent, session = await _ready_proposal(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    _, consent = await _consent(service, ctx, agent, session)
    with (
        patch("app.services.improvement_pipeline.agent_repo.lock", AsyncMock(return_value=None)),
        pytest.raises(NotFoundError, match="Agent"),
    ):
        if operation == "finish":
            await service.finish(ctx, agent.id, session.id, ImprovementFinish(confirmed=True))
        elif operation == "continue":
            await service.continue_run(ctx, agent.id, session.id, consent)
        else:
            await service.discard(ctx, agent.id, session.id, ImprovementDiscard(confirmed=True))


@pytest.mark.security
async def test_paid_restarts_recheck_ai_assistance_and_refuse_an_unstarted_round(
    db: AsyncSession,
) -> None:
    ctx, agent, session = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    organization = await db.get(Organization, ctx.organization_id)
    assert organization is not None
    organization.ai_assistance_enabled = False
    await db.flush()
    with pytest.raises(AuthorizationError, match="disabled"):
        await service.estimate_continuation(
            ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal("5"))
        )
    organization.ai_assistance_enabled = True
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.iteration = 2
    row.max_iterations = 3
    await db.flush()
    with pytest.raises(NotFoundError, match="round"):
        await service.estimate_continuation(
            ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal("5"))
        )


async def test_recovery_sweeps_queue_active_and_waiting_sessions_without_new_paid_requests(
    db: AsyncSession,
) -> None:
    ctx, agent, _, queued = await _started(db)
    other_ctx, _, ready = await _ready_proposal(db)
    requests = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    service = ImprovementPipelineService(db)
    assert await service.sweep() == 2
    assert await service.sweep() == 2
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == requests
    assert (await service.read(ctx, agent.id, queued.id)).status == "queued"
    await service.advance(uuid4(), other_ctx.organization_id)


@pytest.mark.security
async def test_a_knowledge_source_reader_without_run_permission_returns_nothing(
    db: AsyncSession,
) -> None:
    ctx, agent, dataset, session = await _started(db)
    limited = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW}))
    assert await ImprovementPipelineService(db)._knowledge_sources(
        limited, agent, dataset_id=dataset.id
    ) == ([], [], [])
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.chat_evidence_run_ids = []
    await db.flush()
    assert await ImprovementPipelineService(db).knowledge_sources(ctx, row) == ([], [], [])


async def test_a_suite_session_pins_check_settings_but_ignores_a_display_name_change(
    db: AsyncSession,
) -> None:
    from app.db.models.eval_suite import EvalSuite
    from app.schemas.eval_suite import EvalSuiteCreate
    from app.schemas.improvement import ImprovementStart
    from app.services.eval_suite import EvalSuiteService

    ctx, agent, dataset, original = await _started(db)
    service = ImprovementPipelineService(db)
    await service.cancel(ctx, agent.id, original.id)
    suite = await EvalSuiteService(db).create(
        ctx, agent.id, EvalSuiteCreate(name="Pinned questions", dataset_id=dataset.id)
    )
    session = await service.start(
        ctx,
        agent.id,
        ImprovementStart(suite_id=suite.id, max_iterations=1, budget_usd=Decimal("5")),
    )
    stored = await db.get(EvalSuite, suite.id)
    assert stored is not None
    stored.name = "A clearer display name"
    await db.flush()
    await service.ensure_current(ctx, session.id)
    stored.min_pass_rate = Decimal("0.9")
    await db.flush()
    with pytest.raises(ConcurrentChangeError, match="stale"):
        await service.ensure_current(ctx, session.id)


@pytest.mark.parametrize("child", ["check", "proposal", "classify", "draft"])
async def test_continuation_waits_for_every_existing_paid_child(
    db: AsyncSession, child: str
) -> None:
    from app.db.models.background_job import BackgroundJob

    ctx, agent, session = await _ready_proposal(db)
    row = await db.get(ImprovementRun, session.id)
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=session.id, number=1
    )
    assert row is not None and iteration is not None
    row.max_iterations = 3
    if child == "proposal":
        request = await db.get(AuthoringRequest, iteration.authoring_request_id)
        assert request is not None
        request.status = "running"
    elif child in {"classify", "draft"}:
        job = BackgroundJob(
            kind="improvement_classify" if child == "classify" else "improvement_draft",
            pool="agent",
            organization_id=ctx.organization_id,
            max_attempts=1,
        )
        db.add(job)
        await db.flush()
        if child == "classify":
            iteration.classify_job_id = job.id
        else:
            iteration.draft_job_id = job.id
    await db.flush()
    service = ImprovementPipelineService(db)
    before = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    with (
        patch(
            "app.services.improvement_pipeline.improvement_repo.has_active_check",
            AsyncMock(return_value=child == "check"),
        ),
        pytest.raises(ConcurrentChangeError, match="Wait"),
    ):
        await service.estimate_continuation(
            ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal("5"))
        )
    assert row.status == "ready" and row.iteration == 1
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == before


@pytest.mark.security
@pytest.mark.parametrize("candidate", ["missing", "changed"])
async def test_budget_resume_requires_the_same_existing_candidate(
    db: AsyncSession, candidate: str
) -> None:
    ctx, agent, session = await _ready_proposal(db)
    row = await db.get(ImprovementRun, session.id)
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=session.id, number=1
    )
    assert row is not None and iteration is not None
    row.status, row.stage, row.stop_reason = "stopped", "evaluating", "budget"
    before = list(iteration.eval_run_ids)
    if candidate == "missing":
        iteration.batch_id = None
    else:
        iteration.candidate_spec_hash = "0" * 64
    await db.flush()
    expected = NotFoundError if candidate == "missing" else ConcurrentChangeError
    with pytest.raises(expected, match=r"candidate|suggestions"):
        await ImprovementPipelineService(db).estimate_continuation(
            ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal("5"))
        )
    assert row.status == "stopped" and iteration.eval_run_ids == before


async def test_a_failed_unmeasured_knowledge_step_requires_a_new_session(
    db: AsyncSession,
) -> None:
    ctx, agent, _, session = await _started(db)
    row = await db.get(ImprovementRun, session.id)
    assert row is not None
    row.status, row.stage, row.stop_reason = "failed", "classifying", "proposal"
    await db.flush()
    with pytest.raises(BadRequestError, match="new session"):
        await ImprovementPipelineService(db).estimate_continuation(
            ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal("5"))
        )
    assert row.status == "failed"
