"""Explicit continuation retains the session's sources, costs, identity and limits."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    PaymentRequiredError,
)
from app.core.permissions import Perm
from app.db.models.authoring import AuthoringRequest
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.repositories import authoring_repo, improvement_repo
from app.schemas.api_key import ApiKeyCreate
from app.schemas.authoring import AuthoringEstimate, HunkDecision
from app.schemas.improvement import ContinuationConsent, ImprovementContinue, ImprovementDiscard
from app.services.api_key import ApiKeyService
from app.services.authoring import AuthoringService
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import Improver, _improve
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_improvement_pipeline import _ready_proposal, _started, _until_child

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _consent(service, ctx, agent, session, budget="5"):
    quote = await service.estimate_continuation(
        ctx, agent.id, session.id, ImprovementContinue(budget_usd=Decimal(budget))
    )
    return quote, ContinuationConsent(
        confirmed=True,
        budget_usd=quote.budget_usd,
        estimate_usd=quote.total_usd,
        candidate_hash=quote.candidate_hash,
    )


async def test_consent_starts_one_next_round_without_accepting_or_replacing_the_previous_candidate(
    db,
):
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    quote, consent = await _consent(service, ctx, agent, ready)
    assert quote.mode == "next_round" and quote.number == 2 and quote.affordable
    assert len((await service.read(ctx, agent.id, ready.id)).iterations) == 1
    before = dict(agent.draft_spec)
    requests = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    started = await service.continue_run(ctx, agent.id, ready.id, consent)
    assert started.status == "running" and started.iteration == 2 and started.stage == "proposing"
    assert (await service.continue_run(ctx, agent.id, ready.id, consent)).iteration == 2
    for _ in range(2):
        await service.advance(ready.id, ctx.organization_id)
    current = await service.read(ctx, agent.id, ready.id)
    assert len(current.iterations) == 2
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == requests + 1
    assert current.iterations[0].eval_run_ids == ready.iterations[0].eval_run_ids
    assert current.spent_usd == ready.spent_usd
    old_batch = await authoring_repo.get_batch(
        db, ready.iterations[0].batch_id, organization_id=ctx.organization_id
    )
    assert old_batch.status == "open"
    assert agent.draft_spec == before


@pytest.mark.security
async def test_budget_resume_preserves_old_checks_and_starts_only_one_new_check(db):
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    row.status, row.stage, row.stop_reason = "stopped", "evaluating", "budget"
    row.budget_usd = ready.spent_usd
    await db.flush()
    service = ImprovementPipelineService(db)
    quote, consent = await _consent(service, ctx, agent, ready)
    assert quote.mode == "resume" and quote.number == 1
    assert row.budget_usd == ready.spent_usd
    before = await db.scalar(select(func.count()).select_from(EvalRun))
    started = await service.continue_run(ctx, agent.id, ready.id, consent)
    assert started.budget_usd == Decimal(5) and started.status == "running"
    assert len(started.iterations[0].eval_run_ids) == 2
    assert started.iterations[0].eval_run_ids[0] == ready.iterations[0].eval_run_ids[0]
    await service.continue_run(ctx, agent.id, ready.id, consent)
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == before + 1


async def test_a_failed_proposal_retry_gets_a_new_child_within_the_same_round(db):
    ctx, agent, _, initial = await _started(db)
    await _until_child(db, ctx, initial.id)
    service = ImprovementPipelineService(db)
    current = await service.read(ctx, agent.id, initial.id)
    old_id = current.iterations[0].authoring_request_id
    request = await db.get(AuthoringRequest, old_id)
    request.status = "failed"
    await db.flush()
    await service.advance(initial.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, initial.id)).status == "failed"
    quote, consent = await _consent(service, ctx, agent, initial)
    assert quote.mode == "retry" and quote.number == 1
    await service.continue_run(ctx, agent.id, initial.id, consent)
    await service.advance(initial.id, ctx.organization_id)
    retried = await service.read(ctx, agent.id, initial.id)
    assert retried.iteration == 1 and len(retried.iterations) == 1
    assert retried.iterations[0].authoring_request_id != old_id
    assert request.status == "failed"


@pytest.mark.parametrize("reason", ["repeat_candidate", "inconclusive", "max_iterations"])
@pytest.mark.security
async def test_hard_stop_conditions_cannot_be_bypassed_by_increasing_the_budget(db, reason):
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    row.status, row.stop_reason = "stopped", reason
    await db.flush()
    with pytest.raises(BadRequestError):
        await ImprovementPipelineService(db).estimate_continuation(
            ctx, agent.id, ready.id, ImprovementContinue(budget_usd=Decimal("10"))
        )
    assert row.budget_usd == Decimal(5)
    assert (
        len(
            await improvement_repo.list_iterations(
                db, organization_id=ctx.organization_id, run_id=ready.id
            )
        )
        == 1
    )


async def test_changed_quotes_and_insufficient_limits_start_no_paid_work(db):
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    low, consent = await _consent(service, ctx, agent, ready, budget=str(ready.spent_usd))
    assert not low.affordable
    with pytest.raises(PaymentRequiredError):
        await service.continue_run(ctx, agent.id, ready.id, consent)
    _, valid = await _consent(service, ctx, agent, ready)
    with pytest.raises(ConcurrentChangeError):
        await service.continue_run(
            ctx, agent.id, ready.id, valid.model_copy(update={"estimate_usd": Decimal(0)})
        )
    iteration = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=ready.id, number=1
    )
    iteration.verdict_detail = {**iteration.verdict_detail, "fixed": 2}
    await db.flush()
    with pytest.raises(ConcurrentChangeError):
        await service.continue_run(ctx, agent.id, ready.id, valid)
    assert (
        len(
            await improvement_repo.list_iterations(
                db, organization_id=ctx.organization_id, run_id=ready.id
            )
        )
        == 1
    )


async def test_a_different_key_takes_the_session_over_but_not_the_requesters_rechecks(db):
    from tests.integration.test_improvement_selection import _consent as selection_consent
    from tests.integration.test_improvement_selection import _hunks

    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    _, consent = await _consent(service, ctx, agent, ready)
    key = await ApiKeyService(db).create(
        ctx,
        ApiKeyCreate(
            name="narrower",
            scopes=[
                Perm.AGENTS_VIEW,
                Perm.AGENTS_EDIT,
                Perm.AGENTS_RUN,
                Perm.RUNS_VIEW,
                Perm.DATASETS_RUN,
            ],
        ),
    )
    keyed = await ApiKeyService(db).context_for_key(key.id, organization_id=ctx.organization_id)
    read = await service.read(keyed, agent.id, ready.id)
    assert read.can_restart and read.can_discard
    chosen = await selection_consent(
        service, ctx, agent, ready, [(await _hunks(db, ctx, ready))[0].id]
    )
    with pytest.raises(AuthorizationError, match="original account and credentials"):
        await service.check_selection(keyed, agent.id, ready.id, 1, chosen)
    continued = await service.continue_run(keyed, agent.id, ready.id, consent)
    assert continued.status == "running"
    assert (row.actor_user_id, row.actor_api_key_id) == (ctx.user_id, key.id)


async def test_discard_dismisses_only_this_sessions_pending_candidates_and_is_idempotent(db):
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    row.status, row.stop_reason = "stopped", "no_change"
    own = await authoring_repo.get_batch(
        db, ready.iterations[0].batch_id, organization_id=ctx.organization_id
    )
    own.status = "candidate"
    await db.flush()
    await _improve(db, ctx, agent, Improver(db))
    personal = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert personal.id != own.id
    before = dict(agent.draft_spec)
    service = ImprovementPipelineService(db)
    discarded = await service.discard(ctx, agent.id, ready.id, ImprovementDiscard(confirmed=True))
    assert discarded.status == "rejected"
    repeated = await service.discard(ctx, agent.id, ready.id, ImprovementDiscard(confirmed=True))
    assert repeated.status == "rejected"
    await db.refresh(own)
    await db.refresh(personal)
    assert own.status == "superseded" and personal.status == "open"
    assert all(
        h.status == "dismissed"
        for h in await authoring_repo.list_hunks(
            db, organization_id=ctx.organization_id, batch_id=own.id
        )
    )
    assert all(
        h.status == "pending"
        for h in await authoring_repo.list_hunks(
            db, organization_id=ctx.organization_id, batch_id=personal.id
        )
    )
    assert agent.draft_spec == before and discarded.spent_usd == ready.spent_usd


async def test_discard_does_not_undo_a_change_somebody_already_applied(db):
    ctx, agent, ready = await _ready_proposal(db)
    hunks = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=ready.iterations[0].batch_id
    )
    instruction = next(h for h in hunks if h.kind == "instructions")
    await AuthoringService(db).decide(ctx, agent.id, instruction.id, HunkDecision(action="accept"))
    with pytest.raises(BadRequestError, match="already applied"):
        await ImprovementPipelineService(db).discard(
            ctx, agent.id, ready.id, ImprovementDiscard(confirmed=True)
        )
    assert "30 days" in AgentSpec.model_validate(agent.draft_spec).instructions


async def test_two_inconclusive_measurements_stop_without_another_paid_proposal(db):
    from unittest.mock import AsyncMock, patch

    from app.db.models.case_score import CaseScore
    from app.repositories import eval_run_repo
    from app.services.agent_runner import AgentRunnerService
    from app.services.eval_run_worker import EvalRunWorker
    from tests.integration.test_authoring import _sessions
    from tests.integration.test_improvement_pipeline import Answers

    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    row.max_iterations, row.status, row.stage = 3, "running", "judging"

    async def ungrade(check_id):
        scores = list(
            (await db.scalars(select(CaseScore).where(CaseScore.eval_run_id == check_id))).all()
        )
        for score in scores:
            score.passed, score.results = None, []
        await db.flush()
        await eval_run_repo.forget_outcomes(db, [check_id], organization_id=ctx.organization_id)

    await ungrade(ready.iterations[0].eval_run_ids[-1])
    service = ImprovementPipelineService(db)
    await service.advance(ready.id, ctx.organization_id)
    await service.advance(ready.id, ctx.organization_id)
    repeating = await service.read(ctx, agent.id, ready.id)
    assert len(repeating.iterations[0].eval_run_ids) == 2
    model = Answers(db)

    async def execute(runner, *args, **kwargs):
        return await model.execute(runner, *args, **kwargs)

    with (
        patch.object(AgentRunnerService, "execute", new=execute),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            repeating.iterations[0].eval_run_ids[-1],
            ctx.organization_id,
            sessions=_sessions(db),
            sleep=AsyncMock(),
        ).run()
    await ungrade(repeating.iterations[0].eval_run_ids[-1])
    requests = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    await service.advance(ready.id, ctx.organization_id)
    await service.advance(ready.id, ctx.organization_id)
    stopped = await service.read(ctx, agent.id, ready.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "inconclusive")
    assert stopped.iteration == 1 and len(stopped.iterations) == 1
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == requests


@pytest.mark.security
async def test_a_budget_stopped_classifier_is_resumed_under_a_fresh_quote(db):
    from app.worker.tasks.knowledge_gap_tasks import classify_knowledge_gaps
    from tests.integration.test_improvement_knowledge_steps import _job, _providers, _start, _world

    ctx, agent, _, dataset, _ = await _world(db)
    with _providers(db, ctx):
        read = await _start(db, ctx, agent, dataset)
        row = await db.get(ImprovementRun, read.id)
        old_job, payload = await _job(db, row)
        row.budget_usd = Decimal("0.000001")
        await db.flush()
        assert await classify_knowledge_gaps(payload) == 0
        old_job.status = "succeeded"
        await db.flush()
        service = ImprovementPipelineService(db)
        quote, consent = await _consent(service, ctx, agent, read)
        assert quote.mode == "resume" and quote.affordable
        await service.continue_run(ctx, agent.id, read.id, consent)
        await service.advance(read.id, ctx.organization_id)
        new_job, new_payload = await _job(db, row)
        assert new_job.id != old_job.id
        assert await classify_knowledge_gaps(new_payload) == 2


async def test_another_attempt_with_nothing_left_to_learn_from_says_so(db):
    """Refused for its reason, not as an estimate the budget cannot cover."""
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    nothing = AuthoringEstimate(
        runs=0,
        rated_down=0,
        calls=0,
        estimate_usd=Decimal(0),
        affordable=True,
        reason="no_evidence",
    )
    with (
        patch.object(AuthoringService, "estimate_agent", AsyncMock(return_value=nothing)),
        pytest.raises(BadRequestError, match="nothing to learn from") as refused,
    ):
        await _consent(service, ctx, agent, ready)
    assert refused.value.details == {"reason": "no_evidence"}


async def test_a_session_says_before_try_again_that_it_has_nothing_left_to_learn_from(db):
    from dataclasses import replace

    from app.core.exceptions import AuthorizationError
    from app.schemas.improvement import TryAgainBlocked
    from app.services.authoring_evidence import EvidencePack, EvidenceService

    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    assert (await service.read(ctx, agent.id, ready.id)).try_again_blocked is None

    empty = AsyncMock(return_value=EvidencePack())
    with patch.object(EvidenceService, "for_improvement", empty):
        blocked = await service.read(ctx, agent.id, ready.id)
        assert blocked.try_again_blocked == TryAgainBlocked(reason="nothing_to_learn")
        viewer = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.RUNS_VIEW}))
        assert (await service.read(viewer, agent.id, ready.id)).try_again_blocked is None
        row.max_iterations = 1
        await db.flush()
        assert (await service.read(ctx, agent.id, ready.id)).try_again_blocked is None
        row.max_iterations = 3
        row.status, row.stop_reason = "stopped", "permission"
        await db.flush()
        assert (await service.read(ctx, agent.id, ready.id)).try_again_blocked is None
    row.status, row.stop_reason = "ready", None
    await db.flush()
    unreadable = AsyncMock(side_effect=AuthorizationError(message="No access to the questions"))
    with patch.object(EvidenceService, "for_improvement", unreadable):
        assert (await service.read(ctx, agent.id, ready.id)).try_again_blocked is None


async def test_another_attempt_is_priced_on_the_questions_it_then_learns_from(db):
    """The estimate reads the next attempt's own draw, so it cannot pass while the attempt
    finds nothing to learn from after it is confirmed."""
    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    assert row is not None
    row.max_iterations = 3
    await db.flush()
    service = ImprovementPipelineService(db)
    priced = AsyncMock(wraps=service.authoring.estimate_agent)
    with patch.object(service.authoring, "estimate_agent", priced):
        quote, consent = await _consent(service, ctx, agent, ready)
    assert quote.mode == "next_round"
    started = await service.continue_run(ctx, agent.id, ready.id, consent)

    following = await improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=ready.id, number=started.iteration
    )
    assert following is not None and following.train_case_ids is not None
    assert priced.await_args.kwargs["train_case_ids"] == following.train_case_ids
