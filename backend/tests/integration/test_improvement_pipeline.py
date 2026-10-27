"""The durable pipeline across actual PostgreSQL transactions and scripted model calls."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AuthorizationError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext
from app.db.models.authoring import AuthoringRequest
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.db.models.notification import Notification
from app.db.models.organization import OrganizationMember
from app.repositories import authoring_repo, improvement_repo
from app.schemas.improvement import (
    ContinuationConsent,
    ImprovementContinue,
    ImprovementRead,
    ImprovementStart,
    ImprovementTarget,
)
from app.services.agent_registry import UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.authoring_worker import AuthoringWorker
from app.services.eval_run_worker import EvalRunWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.knowledge_gaps import KnowledgeGapService
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


async def _next_step(
    db: AsyncSession, ctx: AuthContext, run_id: UUID, *, note: str | None = None
) -> ImprovementRead:
    """Take a session's next step - or try again - at its quoted price, as a person does."""
    service = ImprovementPipelineService(db)
    run = await db.get(ImprovementRun, run_id)
    assert run is not None
    quote = await service.estimate_continuation(
        ctx, run.agent_id, run_id, ImprovementContinue(budget_usd=run.budget_usd)
    )
    return await service.continue_run(
        ctx,
        run.agent_id,
        run_id,
        ContinuationConsent(
            confirmed=True,
            budget_usd=quote.budget_usd,
            estimate_usd=quote.total_usd,
            candidate_hash=quote.candidate_hash,
            note=note,
        ),
    )


async def _until_child(db: AsyncSession, ctx: AuthContext, run_id: UUID) -> None:
    """Advance a fresh session to its proposal: through Understand, where it waits."""
    for _ in range(2):
        await ImprovementPipelineService(db).advance(run_id, ctx.organization_id)
    await _next_step(db, ctx, run_id)
    await ImprovementPipelineService(db).advance(run_id, ctx.organization_id)


async def _ready_proposal(db):
    ctx, agent, _, read = await _started(db)
    original = AgentSpec.model_validate(agent.draft_spec)
    version = agent.current_version_id
    await _until_child(db, ctx, read.id)
    first = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert first.stage == "proposing"
    assert first.baseline_answers is None and first.candidate_answers is None
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
    waiting = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert (waiting.status, waiting.stage, waiting.next_step) == ("waiting", "filtering", "check")
    await _next_step(db, ctx, read.id)
    evaluating = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    [eval_id] = evaluating.iterations[0].eval_run_ids
    for side in (evaluating.baseline_answers, evaluating.candidate_answers):
        assert side is not None and side.answered == 0 < side.total and not side.reused
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
    for before, after in (
        (evaluating.baseline_answers, ready.baseline_answers),
        (evaluating.candidate_answers, ready.candidate_answers),
    ):
        assert before is not None
        assert after == before.model_copy(update={"answered": before.total})
    assert AgentSpec.model_validate(agent.draft_spec) == original
    assert agent.current_version_id == version
    batch = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert batch is not None and batch.id == ready.iterations[0].batch_id
    assert ready.spent_usd > Decimal("0.02")
    assert ready.best_iteration_id == ready.iterations[0].id
    assert len(ready.timeline) >= 9
    notices = (
        await db.scalars(
            select(Notification).where(Notification.event_type == "improvement_finished")
        )
    ).all()
    assert any("ready" in notice.summary for notice in notices)
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, read.id)).status == "ready"

    return ctx, agent, ready


async def test_a_session_waiting_for_a_person_is_listed_only_where_its_agent_is_readable(db):
    from dataclasses import replace

    from app.core.permissions import Perm

    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    [listed] = await service.awaiting(ctx)
    assert (listed.id, listed.agent_id, listed.agent_name) == (ready.id, agent.id, agent.name)
    assert listed.status == "ready" and listed.iteration == 1

    async def unreadable(*_args: object, **_kwargs: object) -> None:
        raise NotFoundError(message="Agent not found")

    with patch.object(service.registry, "get", unreadable):
        assert await service.awaiting(ctx) == []
    no_runs = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW}))
    with pytest.raises(AuthorizationError, match="runs:view"):
        await service.awaiting(no_runs)
    run = await db.get(ImprovementRun, ready.id)
    run.status = "published"
    await db.flush()
    assert await service.awaiting(ctx) == []


async def test_the_before_answers_are_counted_where_a_reused_baseline_gave_them(db):
    from app.db.models.eval_run import ArmRole, EvalRunArm, EvalRunCase
    from app.repositories import eval_run_repo

    ctx, _, ready = await _ready_proposal(db)
    [eval_id] = ready.iterations[0].eval_run_ids
    arms = {
        arm.role: arm
        for arm in await eval_run_repo.list_arms(db, [eval_id], organization_id=ctx.organization_id)
    }
    baseline, candidate = arms["baseline"], arms["candidate"]
    org = ctx.organization_id
    answered = await eval_run_repo.arm_answers(
        db, eval_id, role=ArmRole.BASELINE, organization_id=org
    )
    assert answered is not None and answered.answered == answered.total > 0
    assert not answered.reused
    await db.execute(delete(EvalRunCase).where(EvalRunCase.arm_id == baseline.id))
    assert await eval_run_repo.arm_answers(
        db, eval_id, role=ArmRole.BASELINE, organization_id=org
    ) == (0, 0, False)
    await db.execute(
        update(EvalRunArm)
        .where(EvalRunArm.id == baseline.id)
        .values(reused_from_arm_id=candidate.id)
        .execution_options(synchronize_session=False)
    )
    db.expire_all()
    reused = await eval_run_repo.arm_answers(
        db, eval_id, role=ArmRole.BASELINE, organization_id=org
    )
    assert reused is not None and reused.total > 0 and reused.reused
    assert (
        await eval_run_repo.arm_answers(db, uuid4(), role=ArmRole.BASELINE, organization_id=org)
        is None
    )


async def test_ready_proposal_survives_repeated_transitions_without_changing_the_agent(db):
    await _ready_proposal(db)


async def test_every_move_is_announced_to_the_agents_open_pages(db):
    with (
        patch("app.services.improvement_pipeline.change_feed") as feed,
        patch("app.services.improvement_pipeline.spawn_after_commit") as queued,
    ):
        _, agent, ready = await _ready_proposal(db)
    events = [call.args[0] for call in feed.publish.call_args_list]
    assert queued.call_count == len(events) >= 2
    assert {(event.resource, event.id, event.surface) for event in events} == {
        ("improvement", agent.id, "system")
    }
    assert all(event.actor_user_id is None for event in events)
    assert ready.status == "ready"


async def _queued_advances(db: AsyncSession, run_id: UUID) -> int:
    from app.db.models.background_job import BackgroundJob

    return await db.scalar(
        select(func.count())
        .select_from(BackgroundJob)
        .where(
            BackgroundJob.kind == "advance-improvement",
            BackgroundJob.status == "queued",
            BackgroundJob.payload["run_id"].astext == str(run_id),
        )
    )


async def _settle_queued_jobs(db: AsyncSession) -> None:
    from sqlalchemy import update

    from app.db.models.background_job import BackgroundJob

    await db.execute(
        update(BackgroundJob).where(BackgroundJob.status == "queued").values(status="succeeded")
    )


async def test_an_ended_step_wakes_its_session_instead_of_waiting_for_the_sweep(db):
    from app.db.models.eval_run import EvalRun as EvalRunRow
    from app.services.notifications import NotificationService

    ctx, agent, _, read = await _started(db)
    await _until_child(db, ctx, read.id)
    proposing = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    request = await db.get(AuthoringRequest, proposing.iterations[0].authoring_request_id)
    await _settle_queued_jobs(db)
    await AuthoringWorker._fail(db, request, "The improver could not answer.")
    assert await _queued_advances(db, read.id) == 1

    await _settle_queued_jobs(db)
    check = EvalRunRow(
        id=uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        status="completed",
        purpose="gate",
        created_by_user_id=ctx.user_id,
        proposal_check={"improvement_run_id": str(read.id)},
    )
    with patch(
        "app.services.notifications.spawn_after_commit",
        side_effect=lambda _db, coro, *, name: coro.close(),
    ):
        await NotificationService(db).eval_run_finished(check)
    assert await _queued_advances(db, read.id) == 1

    await ImprovementPipelineService(db).cancel(ctx, agent.id, read.id)
    await _settle_queued_jobs(db)
    await ImprovementPipelineService(db).wake(read.id, organization_id=ctx.organization_id)
    await ImprovementPipelineService(db).wake(read.id, organization_id=uuid4())
    assert await _queued_advances(db, read.id) == 0


async def test_failed_paid_attempt_does_not_spend_the_confirming_measurement(db):
    ctx, _, read = await _ready_proposal(db)
    ids = read.iterations[0].eval_run_ids
    assert (
        await improvement_repo.completed_checks(db, ids, organization_id=ctx.organization_id) == 1
    )
    assert await improvement_repo.completed_checks(db, ids, organization_id=uuid4()) == 0
    child = await db.get(EvalRun, ids[0])
    child.status = "failed"
    await db.flush()
    assert (
        await improvement_repo.completed_checks(db, ids, organization_id=ctx.organization_id) == 0
    )
    assert await improvement_repo.completed_checks(db, [], organization_id=ctx.organization_id) == 0


async def test_confirmed_finish_accepts_and_publishes_through_normal_path(db):
    from app.schemas.improvement import ImprovementFinish
    from app.services.eval_suite import EvalSuiteService

    ctx, agent, ready = await _ready_proposal(db)
    before = agent.current_version_id
    assert ready.offer_automatic_check
    assert ready.next_version is not None
    result = await ImprovementPipelineService(db).finish(
        ctx,
        agent.id,
        ready.id,
        ImprovementFinish(confirmed=True, publish=True, automatic_check=True),
    )
    assert result.session.status == "published"
    reopened = await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)
    assert reopened.published_version_id == result.version_id
    assert reopened.published_version == result.version
    assert not reopened.offer_automatic_check
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
    # The session is priced to its first stop; each attempt is priced when it is taken.
    assert estimate.total_usd == estimate.knowledge_usd == 0
    assert estimate.per_round_usd == estimate.proposal_usd + 2 * estimate.eval_usd
    assert estimate.estimated_minutes >= 3
    assert await db.scalar(select(func.count()).select_from(ImprovementRun)) == 1


@pytest.mark.security
async def test_an_editor_who_cannot_read_runs_is_told_why_before_any_estimate_or_start(db):
    from dataclasses import replace

    from app.core.permissions import Perm

    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=5)
    editor = replace(
        ctx,
        key_scopes=frozenset(
            {Perm.AGENTS_VIEW, Perm.AGENTS_EDIT, Perm.DATASETS_VIEW, Perm.DATASETS_RUN}
        ),
    )
    service = ImprovementPipelineService(db)
    target = ImprovementTarget(dataset_id=dataset.id)
    with pytest.raises(AuthorizationError) as estimate:
        await service.estimate(editor, agent.id, target)
    with pytest.raises(AuthorizationError) as start:
        await service.start(
            editor,
            agent.id,
            ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal("5")),
        )
    for refused in (estimate.value, start.value):
        assert refused.message == "Improving an agent needs runs:view"
        assert refused.details == {"permission": "runs:view"}
    assert await db.scalar(select(func.count()).select_from(ImprovementRun)) == 0


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


@pytest.mark.security
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


@pytest.mark.security
async def test_budget_is_checked_again_before_the_paid_proposal(db):
    ctx, agent, _, read = await _started(db)
    for _ in range(2):
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    await _next_step(db, ctx, read.id)
    row = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert row is not None
    row.budget_usd = Decimal("0.000001")
    await db.flush()
    await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    stopped = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "budget")
    assert stopped.iterations[0].authoring_request_id is None


@pytest.mark.security
async def test_start_refuses_unfunded_session_and_private_progress_cannot_cross_tenants(db):
    ctx, agent, dataset, read = await _started(db)
    stranger = await _owner(db)
    with pytest.raises(NotFoundError):
        await ImprovementPipelineService(db).read(stranger, agent.id, read.id)
    with pytest.raises(NotFoundError):
        await ImprovementPipelineService(db).cancel(stranger, agent.id, read.id)
    await ImprovementPipelineService(db).cancel(ctx, agent.id, read.id)
    sorting = AsyncMock(return_value=Decimal("0.01"))
    with (
        patch.object(KnowledgeGapService, "improvement_estimate", sorting),
        pytest.raises(PaymentRequiredError),
    ):
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


@pytest.mark.security
async def test_a_check_over_the_budget_is_refused_and_the_session_keeps_waiting(db):
    ctx, agent, _, read = await _started(db)
    await _until_child(db, ctx, read.id)
    before = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    request_id = before.iterations[0].authoring_request_id
    assert request_id is not None
    with _answering(Improver(db)):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    for _ in range(2):
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    service = ImprovementPipelineService(db)
    tight = ImprovementContinue(budget_usd=Decimal("0.020001"))
    quote = await service.estimate_continuation(ctx, agent.id, read.id, tight)
    assert quote.mode == "next_step" and not quote.affordable
    with pytest.raises(PaymentRequiredError):
        await service.continue_run(
            ctx,
            agent.id,
            read.id,
            ContinuationConsent(
                confirmed=True,
                budget_usd=tight.budget_usd,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
            ),
        )
    waiting = await service.read(ctx, agent.id, read.id)
    assert (waiting.status, waiting.stage) == ("waiting", "filtering")
    assert not waiting.iterations[0].eval_run_ids
    assert waiting.spent_usd == Decimal("0.02")
    # A check the session starts itself - an inconclusive result's repeat - is
    # held to the budget again before it starts.
    row = await improvement_repo.get_run(db, read.id, organization_id=ctx.organization_id)
    assert row is not None
    row.status, row.stage, row.budget_usd = "running", "evaluating", Decimal("0.020001")
    await db.flush()
    await service.advance(read.id, ctx.organization_id)
    stopped = await service.read(ctx, agent.id, read.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "budget")
    assert not stopped.iterations[0].eval_run_ids


@pytest.mark.security
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


async def _model_and_content_candidate(db):
    """A first round proposing another model and a new description together."""
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
    return ctx, agent, row, iteration, model_id


async def test_model_changes_get_a_candidate_of_their_own(db):
    ctx, agent, row, iteration, model_id = await _model_and_content_candidate(db)
    row.max_iterations = iteration.number + 1
    await db.flush()
    projected, count = await ImprovementPipelineService(db)._candidate(
        agent, row, iteration, filter_policy=True
    )
    assert count == 1
    assert projected.model_profile_id == model_id
    assert projected.description is None
    [first, deferred] = await improvement_repo.list_iterations(
        db, organization_id=ctx.organization_id, run_id=row.id
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


async def test_the_last_attempt_measures_a_model_change_with_the_rest(db):
    """No attempt is left to measure the rest apart, so nothing is set aside for one."""
    ctx, agent, row, iteration, model_id = await _model_and_content_candidate(db)
    row.max_iterations = iteration.number
    await db.flush()
    projected, count = await ImprovementPipelineService(db)._candidate(
        agent, row, iteration, filter_policy=True
    )
    assert count == 2
    assert projected.model_profile_id == model_id
    assert projected.description == "Refund questions"
    assert [
        item.number
        for item in await improvement_repo.list_iterations(
            db, organization_id=ctx.organization_id, run_id=row.id
        )
    ] == [1]


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


async def test_existing_suite_is_not_offered_or_duplicated_on_finish(db):
    from app.schemas.eval_suite import EvalSuiteCreate
    from app.schemas.improvement import ImprovementFinish
    from app.services.eval_suite import EvalSuiteService

    ctx, agent, ready = await _ready_proposal(db)
    suites = EvalSuiteService(db)
    existing = await suites.create(
        ctx, agent.id, EvalSuiteCreate(name="Existing checks", dataset_id=ready.dataset_id)
    )
    service = ImprovementPipelineService(db)
    reopened = await service.read(ctx, agent.id, ready.id)
    assert not reopened.offer_automatic_check
    await service.finish(
        ctx, agent.id, ready.id, ImprovementFinish(confirmed=True, automatic_check=True)
    )
    assert [s.id for s in (await suites.list_for_agent(ctx, agent.id)).items] == [existing.id]
