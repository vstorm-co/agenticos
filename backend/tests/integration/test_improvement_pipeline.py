"""The durable pipeline across actual PostgreSQL transactions and scripted model calls."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext
from app.db.models.authoring import AuthoringRequest
from app.db.models.improvement import ImprovementRun
from app.db.models.notification import Notification
from app.db.models.organization import OrganizationMember
from app.repositories import authoring_repo, improvement_repo
from app.schemas.improvement import ImprovementStart, ImprovementTarget
from app.services.agent_registry import UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.authoring_worker import AuthoringWorker
from app.services.eval_run_worker import EvalRunWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import (
    Improver,
    _answering,
    _sessions,
    _setup,
)
from tests.integration.test_authoring import (
    _environment as _environment,
)
from tests.integration.test_eval_suites import Model, _dataset, _owner

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _started(db: AsyncSession):
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=5)
    service = ImprovementPipelineService(db)
    read = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
    )
    return ctx, agent, dataset, read


class Answers(Model):
    async def execute(
        self,
        runner: AgentRunnerService,
        ctx: AuthContext,
        agent_id: UUID,
        prompt: str,
        **kw: object,
    ):
        candidate = kw["candidate"]
        assert isinstance(candidate, UnpublishedCandidate)
        _, run = await super().execute(runner, ctx, agent_id, prompt, **kw)
        answer = "30 days" if "30 days" in candidate.spec.instructions else "90 days"
        return answer, run


async def _until_child(db: AsyncSession, ctx: AuthContext, run_id: UUID) -> None:
    for _ in range(3):
        await ImprovementPipelineService(db).advance(run_id, ctx.organization_id)


async def _ready_proposal(db):
    ctx, agent, _, read = await _started(db)
    original = AgentSpec.model_validate(agent.draft_spec)
    version = agent.current_version_id
    await _until_child(db, ctx, read.id)
    first = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert first.stage == "proposing"
    request_id = first.iterations[0].authoring_request_id
    assert request_id is not None
    for _ in range(2):
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AuthoringRequest)
            .where(AuthoringRequest.improvement_run_id == read.id)
        )
        == 1
    )
    with _answering(Improver(db)):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    filtered = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert filtered.stage == "filtering"
    assert (
        await authoring_repo.get_open_batch(
            db, organization_id=ctx.organization_id, agent_id=agent.id
        )
        is None
    )
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    evaluating = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    [eval_id] = evaluating.iterations[0].eval_run_ids
    # A worker restart sees the existing child, even before it has been claimed.
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, read.id)).iterations[
        0
    ].eval_run_ids == [eval_id]
    model = Answers(db)

    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    with (
        patch.object(AgentRunnerService, "execute", new=execute),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            eval_id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    ready = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert ready.status == "ready", ready
    assert AgentSpec.model_validate(agent.draft_spec) == original
    assert agent.current_version_id == version
    batch = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert batch is not None and batch.id == ready.iterations[0].batch_id
    assert ready.spent_usd > Decimal("0.02")
    assert ready.best_iteration_id == ready.iterations[0].id
    assert len(ready.timeline) >= 9
    notice = await db.scalar(
        select(Notification).where(Notification.event_type == "improvement_finished")
    )
    assert notice is not None and "ready" in notice.summary
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, read.id)).status == "ready"

    return ctx, agent, ready


async def test_ready_proposal_survives_repeated_transitions_without_changing_the_agent(db):
    await _ready_proposal(db)


async def test_confirmed_finish_accepts_and_publishes_through_normal_path(db):
    from app.schemas.improvement import ImprovementFinish
    from app.services.eval_suite import EvalSuiteService

    ctx, agent, ready = await _ready_proposal(db)
    before = agent.current_version_id
    result = await ImprovementPipelineService(db).finish(
        ctx,
        agent.id,
        ready.id,
        ImprovementFinish(confirmed=True, publish=True, automatic_check=True),
    )
    assert result.session.status == "published"
    assert result.version_id is not None and result.version_id != before
    assert "30 days" in AgentSpec.model_validate(agent.draft_spec).instructions
    suites = await EvalSuiteService(db).list_for_agent(ctx, agent.id)
    assert suites.total == 1
    assert suites.items[0].on_publish
    assert suites.items[0].threshold.max_confirmed_regressions == 0
    with pytest.raises(ConcurrentChangeError):
        await ImprovementPipelineService(db).finish(
            ctx, agent.id, ready.id, ImprovementFinish(confirmed=True, publish=True)
        )


async def test_keep_as_draft_never_publishes(db):
    from app.schemas.improvement import ImprovementFinish

    ctx, agent, ready = await _ready_proposal(db)
    before = agent.current_version_id
    result = await ImprovementPipelineService(db).finish(
        ctx, agent.id, ready.id, ImprovementFinish(confirmed=True)
    )
    assert result.session.status == "accepted"
    assert result.version_id is None and agent.current_version_id == before


async def test_second_start_is_a_conflict_and_estimate_writes_nothing(db):
    ctx, agent, dataset, read = await _started(db)
    service = ImprovementPipelineService(db)
    with pytest.raises(ConcurrentChangeError) as refused:
        await service.start(
            ctx,
            agent.id,
            ImprovementStart(dataset_id=dataset.id, max_iterations=1, budget_usd=Decimal("5")),
        )
    assert refused.value.details["improvement_run_id"] == str(read.id)
    estimate = await service.estimate(
        ctx, agent.id, ImprovementTarget(dataset_id=dataset.id, max_iterations=2)
    )
    assert estimate.total_usd == estimate.per_round_usd * 2
    assert estimate.per_round_usd == estimate.proposal_usd + 2 * estimate.eval_usd
    assert await db.scalar(select(func.count()).select_from(ImprovementRun)) == 1


@pytest.mark.parametrize("change", ["draft", "publish", "scoring", "archive"])
async def test_changed_inputs_stop_the_session_as_stale(db, change: str):
    from app.db.models.agent import AgentVersion

    ctx, agent, dataset, read = await _started(db)
    if change == "draft":
        agent.draft_spec = {**agent.draft_spec, "instructions": "A newer manual decision"}
    elif change == "publish":
        db.add(
            AgentVersion(
                agent_id=agent.id,
                organization_id=ctx.organization_id,
                version=2,
                spec=agent.draft_spec,
            )
        )
    elif change == "scoring":
        dataset.scoring = {
            "judge": {"criteria": [{"name": "new", "description": "Changed grading"}]}
        }
    else:
        agent.status = "archived"
    await db.flush()
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    row = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert row is not None and row.status == "stale"


async def test_worker_rebuilds_permissions_and_cancel_remains_available_to_creator(db):
    ctx, agent, _, read = await _started(db)
    membership = await db.scalar(
        select(OrganizationMember).where(OrganizationMember.user_id == ctx.user_id)
    )
    assert membership is not None
    membership.role = "viewer"
    await db.flush()
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    stopped = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "permission")
    assert stopped.timeline[-1].reason == "permission"


async def test_budget_is_checked_again_before_the_paid_proposal(db):
    ctx, agent, _, read = await _started(db)
    for _ in range(2):
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    row = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert row is not None
    row.budget_usd = Decimal("0.000001")
    await db.flush()
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    stopped = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "budget")
    assert stopped.iterations[0].authoring_request_id is None


async def test_start_refuses_unfunded_session_and_private_progress_cannot_cross_tenants(db):
    ctx, agent, dataset, read = await _started(db)
    stranger = await _owner(db)
    with pytest.raises(NotFoundError):
        await ImprovementPipelineService(db).read(stranger, agent.id, read.id)
    with pytest.raises(NotFoundError):
        await ImprovementPipelineService(db).cancel(stranger, agent.id, read.id)
    await ImprovementPipelineService(db).cancel(ctx, agent.id, read.id)
    with pytest.raises(PaymentRequiredError):
        await ImprovementPipelineService(db).start(
            ctx, agent.id, ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal("0.000001"))
        )


async def test_stop_cancels_an_authoring_child_without_replacing_a_persons_batch(db):
    ctx, agent, _, read = await _started(db)
    await _until_child(db, ctx, read.id)
    before = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    request_id = before.iterations[0].authoring_request_id
    assert request_id is not None
    stopped = await ImprovementPipelineService(db).cancel(ctx, agent.id, read.id)
    assert stopped.status == "cancelled"
    request = await authoring_repo.get_request(db, request_id, organization_id=ctx.organization_id)
    assert request is not None and request.status == "failed"
    assert (
        await authoring_repo.get_open_batch(
            db, organization_id=ctx.organization_id, agent_id=agent.id
        )
        is None
    )


async def test_an_expensive_eval_is_not_started_after_proposing(db):
    ctx, agent, _, read = await _started(db)
    await _until_child(db, ctx, read.id)
    before = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    request_id = before.iterations[0].authoring_request_id
    assert request_id is not None
    with _answering(Improver(db)):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    for _ in range(2):
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    row = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert row is not None
    row.budget_usd = Decimal("0.020001")
    await db.flush()
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    stopped = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "budget")
    assert not stopped.iterations[0].eval_run_ids
    assert stopped.spent_usd == Decimal("0.02")


async def test_candidate_policy_drops_weakening_and_requires_approval_for_new_mcp_writes(db):
    from app.db.models.authoring import HunkKind
    from app.services.authoring_fields import Staged, stage

    ctx, agent, _, read = await _started(db)
    agent.draft_spec = {
        **agent.draft_spec,
        "capabilities": [{"id": "guardrails"}],
        "mcp_servers": [
            {"account": "personal", "catalog_key": "notion", "allowed_tools": ["search"]}
        ],
    }
    # Pin the test's starting spec before exercising an imported proposal row.
    row = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert row is not None
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=read.id, number=1
    )
    assert iteration is not None
    # No model is needed to exercise the policy boundary.
    batch = await authoring_repo.create_batch(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        request_id=None,
        source_started_at=row.created_at,
        expected_effect="Tighter behavior",
        evidence_conversation_ids=[],
        improvement_run_id=row.id,
    )
    spec = AgentSpec.model_validate(agent.draft_spec)
    staged = stage(
        spec, "mcp_servers/personal:notion/allowed_tools", "set", ["search", "create_page"]
    )
    assert isinstance(staged, Staged)
    hunks = await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=batch.id,
        hunks=[
            {
                "kind": HunkKind.SPEC_FIELD.value,
                "origin": "improve",
                "path": "capabilities",
                "op": "remove",
                "base_value": {"id": "guardrails"},
                "new_value": {"id": "guardrails"},
                "rationale": "Unsafe",
            },
            {
                "kind": HunkKind.SPEC_FIELD.value,
                "origin": "improve",
                "path": "mcp_servers/personal:notion/allowed_tools",
                "op": "set",
                "base_value": ["search"],
                "new_value": ["search", "create_page"],
                "rationale": "Add writing",
            },
        ],
    )
    iteration.batch_id = batch.id
    await db.flush()
    projected, count = await ImprovementPipelineService(db)._candidate(
        agent, row, iteration, filter_policy=True
    )
    assert count == 1
    assert projected.mcp_servers[0].approval == "writes"
    assert [h.id for h in hunks if h.status == "dismissed"] == [hunks[0].id]
    assert iteration.dropped_hunk_ids == [hunks[0].id]
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, read.id)).timeline[
        -1
    ].action == "improvement.policy_dropped"


async def test_model_changes_get_a_candidate_of_their_own(db):
    from uuid import uuid4

    from app.db.models.authoring import HunkKind

    ctx, agent, _, read = await _started(db)
    row = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert row is not None
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=read.id, number=1
    )
    assert iteration is not None
    batch = await authoring_repo.create_batch(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        request_id=None,
        source_started_at=row.created_at,
        expected_effect="Separate model and content checks",
        evidence_conversation_ids=[],
        improvement_run_id=row.id,
    )
    model_id = uuid4()
    await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=batch.id,
        hunks=[
            {
                "kind": HunkKind.SPEC_FIELD.value,
                "origin": "improve",
                "path": "model_profile_id",
                "op": "set",
                "base_value": None,
                "new_value": str(model_id),
                "rationale": "Measure another model",
            },
            {
                "kind": HunkKind.SPEC_FIELD.value,
                "origin": "improve",
                "path": "description",
                "op": "set",
                "base_value": None,
                "new_value": "Refund questions",
                "rationale": "Clarify purpose",
            },
        ],
    )
    iteration.batch_id = batch.id
    await db.flush()
    projected, count = await ImprovementPipelineService(db)._candidate(
        agent, row, iteration, filter_policy=True
    )
    assert count == 1
    assert projected.model_profile_id == model_id
    assert projected.description is None
    [first, deferred] = await improvement_repo.list_iterations(
        db, organization_id=ctx.organization_id, run_id=read.id
    )
    assert first.batch_id != deferred.batch_id and deferred.batch_id is not None
    [content] = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=deferred.batch_id
    )
    assert content.path == "description" and content.status == "pending"
    assert (
        await authoring_repo.get_open_batch(
            db, organization_id=ctx.organization_id, agent_id=agent.id
        )
        is None
    )


async def test_failed_proposal_needs_explicit_retry_and_repeated_click_starts_one_child(db):
    from app.db.models.authoring import AuthoringStatus

    ctx, agent, _, read = await _started(db)
    service = ImprovementPipelineService(db)
    await _until_child(db, ctx, read.id)
    first = await service.read(ctx, agent.id, read.id)
    old_id = first.iterations[0].authoring_request_id
    assert old_id is not None
    request = await authoring_repo.get_request(db, old_id, organization_id=ctx.organization_id)
    assert request is not None
    await authoring_repo.update_request(
        db, request=request, values={"status": AuthoringStatus.FAILED.value}
    )
    await service.advance(read.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, read.id)).status == "failed"
    await service.advance(read.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, read.id)).iterations[0].authoring_request_id == old_id
    retried = await service.retry(ctx, agent.id, read.id)
    new_id = retried.iterations[0].authoring_request_id
    assert new_id is not None and new_id != old_id
    again = await service.retry(ctx, agent.id, read.id)
    assert again.iterations[0].authoring_request_id == new_id
    assert any(event.action == "improvement.retried" for event in again.timeline)


async def test_waiting_session_tracks_human_accept_undo_dismiss_and_publish(db):
    from app.db.models.authoring import BatchStatus, HunkStatus
    from app.db.models.improvement import ImprovementStatus

    ctx, agent, _, read = await _started(db)
    service = ImprovementPipelineService(db)
    await _until_child(db, ctx, read.id)
    first = await service.read(ctx, agent.id, read.id)
    request_id = first.iterations[0].authoring_request_id
    assert request_id is not None
    with _answering(Improver(db)):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    batch = await authoring_repo.batch_for_request(
        db, request_id, organization_id=ctx.organization_id
    )
    assert batch is not None
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=read.id, number=1
    )
    assert iteration is not None
    await improvement_repo.update_iteration(db, iteration=iteration, values={"batch_id": batch.id})
    run = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert run is not None
    await improvement_repo.update_run(
        db,
        run=run,
        values={"status": ImprovementStatus.READY.value, "best_iteration_id": iteration.id},
    )
    hunks = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=batch.id
    )
    for hunk in hunks:
        hunk.status = HunkStatus.ACCEPTED.value
    await db.flush()
    await service.advance(read.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, read.id)).status == "accepted"
    hunks[0].status = HunkStatus.PENDING.value
    await db.flush()
    await service.advance(read.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, read.id)).status == "ready"
    hunks[0].status = HunkStatus.ACCEPTED.value
    batch.status = BatchStatus.PUBLISHED.value
    await db.flush()
    await service.advance(read.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, read.id)).status == "published"
    assert any(
        event.action == "improvement.published"
        for event in (await service.read(ctx, agent.id, read.id)).timeline
    )
