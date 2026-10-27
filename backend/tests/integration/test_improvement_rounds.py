"""Multiple paid rounds retain their own candidates and a blind, frozen control sample."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, ConcurrentChangeError, PaymentRequiredError
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.db.models.notification import Notification
from app.repositories import authoring_repo, improvement_repo
from app.schemas.improvement import (
    AttributionConsent,
    ContinuationConsent,
    ImprovementContinue,
    ImprovementStart,
    NextStepBlocked,
)
from app.services.agent_runner import AgentRunnerService
from app.services.authoring_worker import AuthoringWorker
from app.services.eval_run_worker import EvalRunWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import Improver, _answering, _sessions, _setup
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import Model, _dataset
from tests.integration.test_improvement_pipeline import _next_step

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


class RoundAnswers(Model):
    async def execute(self, runner, ctx, agent_id, prompt, **kw):
        _, run = await super().execute(runner, ctx, agent_id, prompt, **kw)
        spec = kw["candidate"].spec
        improved = "ROUND_GOOD" in spec.instructions
        worsened = "ROUND_BAD" in spec.instructions
        baseline_passes = not prompt.endswith(("6", "7"))
        return ("30 days" if improved or (baseline_passes and not worsened) else "90 days"), run


def _improver(db, marker):
    return Improver(
        db,
        improve={
            "summary": "Repair the training failures",
            "expected_effect": "Correct refund answers",
            "instructions": [
                {
                    "old_text": "Be brief.",
                    "new_text": f"Be brief. {marker}",
                    "rationale": "The training answers fail",
                }
            ],
            "tools": [],
            "fields": [],
        },
    )


async def _round(db, ctx, agent, session_id, marker, *, exhaust_budget=False):
    service = ImprovementPipelineService(db)
    read = await service.read(ctx, agent.id, session_id)
    number = read.iteration
    # Initial analyzing was already done; the next round begins at proposing.
    await service.advance(session_id, ctx.organization_id)
    read = await service.read(ctx, agent.id, session_id)
    request_id = read.iterations[number - 1].authoring_request_id
    assert request_id is not None
    model = _improver(db, marker)
    with _answering(model):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    for _ in range(3):
        await service.advance(session_id, ctx.organization_id)
    read = await service.read(ctx, agent.id, session_id)
    if read.status == "stopped":
        return model
    # A person takes the round on to its check from the Changes stop.
    read = await _next_step(db, ctx, session_id)
    child_id = read.iterations[number - 1].eval_run_ids[-1]
    answers = RoundAnswers(db)

    async def execute(runner, *args, **kwargs):
        return await answers.execute(runner, *args, **kwargs)

    with (
        patch.object(AgentRunnerService, "execute", new=execute),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            child_id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    if exhaust_budget:
        row = await db.get(ImprovementRun, session_id)
        assert row is not None
        row.budget_usd = (await service.read(ctx, agent.id, session_id)).spent_usd
        await db.flush()
    await service.advance(session_id, ctx.organization_id)
    await service.advance(session_id, ctx.organization_id)
    return model


async def _marked_dataset(db, ctx, *, share: Decimal):
    """Eight questions, the stored partition three to learn from and five to measure on,
    with `share` the part a later attempt draws to measure on."""
    dataset = await _dataset(db, ctx, cases=8)
    rows = list(
        await db.scalars(
            select(DatasetCase)
            .where(DatasetCase.dataset_id == dataset.id)
            .order_by(DatasetCase.position)
        )
    )
    for index, row in enumerate(rows):
        row.improvement_partition = "train" if index < 3 else "holdout"
        row.input = f"{'TRAIN' if index < 3 else 'HOLDOUT'}_QUESTION_MARKER_{index}"
    stored = await db.get(Dataset, dataset.id)
    assert stored is not None
    stored.improvement_holdout_share = share
    await db.flush()
    return dataset, [row.case_id for row in rows[3:]]


async def _two_rounds(db):
    ctx, agent, _ = await _setup(db)
    dataset, measured = await _marked_dataset(db, ctx, share=Decimal("0.625"))
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(100), max_iterations=3),
    )
    # queued -> analyzing -> waiting at Understand, before the authoring request exists.
    for _ in range(2):
        await service.advance(started.id, ctx.organization_id)
    await _next_step(db, ctx, started.id)
    first = await _round(db, ctx, agent, started.id, "ROUND_BAD")
    stopped = await service.read(ctx, agent.id, started.id)
    assert (stopped.status, stopped.stop_reason, stopped.iteration) == ("stopped", "regression", 1)
    # The second attempt draws its own five of the eight; which five is fixed here so the
    # questions the better candidate fixes are among them.
    with patch("app.services.improvement_pipeline.drawn_holdout", return_value=measured):
        second_read = await _next_step(db, ctx, started.id, note="KEEP_THE_REFUND_WINDOW_NOTE")
    assert second_read.status == "running" and second_read.iteration == 2
    assert [item.held_out for item in second_read.iterations] == [5, 5]
    second = await _round(db, ctx, agent, started.id, "ROUND_GOOD")
    return ctx, agent, started, first, second


async def test_regression_starts_a_blind_second_round_and_best_is_selectable(db):
    ctx, agent, started, first, second = await _two_rounds(db)
    service = ImprovementPipelineService(db)
    ready = await service.read(ctx, agent.id, started.id)
    assert ready.status == "ready"
    assert [item.verdict for item in ready.iterations] == ["regression", "better"]
    assert ready.best_iteration_id == ready.iterations[1].id
    assert "KEEP_THE_REFUND_WINDOW_NOTE" in "\n".join(second.prompts)
    assert "KEEP_THE_REFUND_WINDOW_NOTE" not in "\n".join(first.prompts)
    assert [item.note for item in ready.iterations] == [None, "KEEP_THE_REFUND_WINDOW_NOTE"]
    # The first attempt learns from the stored partition; the second draws its own.
    assert "HOLDOUT_" not in "\n".join(first.prompts)
    one, two = await improvement_repo.list_iterations(
        db, organization_id=ctx.organization_id, run_id=started.id
    )
    assert one.holdout_case_ids is None and one.split_seed is None
    assert two.holdout_case_ids is not None and two.train_case_ids is not None
    assert len(two.holdout_case_ids) == 5 and len(two.train_case_ids) == 3
    cases = {
        case.case_id: case.input
        for case in await db.scalars(
            select(DatasetCase).where(DatasetCase.dataset_id == started.dataset_id)
        )
    }
    assert set(two.holdout_case_ids) | set(two.train_case_ids) == set(cases)
    assert not any(cases[case_id] in "\n".join(second.prompts) for case_id in two.holdout_case_ids)
    check = await db.get(EvalRun, two.eval_run_ids[-1])
    assert check is not None
    assert check.proposal_check["attempt_holdout"] == [str(i) for i in two.holdout_case_ids]
    assert set(check.proposal_check["measurement"]["holdout_case_ids"]) == {
        str(i) for i in two.holdout_case_ids
    }
    assert [item.verdict_detail["held_out"] for item in ready.iterations] == [5, 5]
    assert [item.held_out for item in ready.iterations] == [5, 5]
    # Training evidence follows the attempt's own learning questions, not the stored partition.
    learned = await service.authoring.evidence.for_improvement(
        ctx, started.id, train_case_ids=two.holdout_case_ids
    )
    assert learned.runs
    assert all(
        "HOLDOUT_" in (item.prompt or "")
        for item in learned.runs
        if item.evidence_kind == "train_eval"
    )
    assert ready.iterations[0].cost_usd > 0 and ready.iterations[1].cost_usd > 0
    assert sum(item.cost_usd for item in ready.iterations) == ready.spent_usd
    assert "ROUND_" not in AgentSpec.model_validate(agent.draft_spec).instructions
    selected = await service.select_round(ctx, agent.id, started.id, 1)
    assert selected.best_iteration_id == ready.iterations[0].id
    current = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert current is not None and current.id == ready.iterations[0].batch_id


async def test_an_attempt_whose_draw_would_leave_too_few_to_measure_is_never_written(db):
    ctx, agent, _ = await _setup(db)
    dataset, _ = await _marked_dataset(db, ctx, share=Decimal("0.5"))
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(100), max_iterations=3),
    )
    for _ in range(2):
        await service.advance(started.id, ctx.organization_id)
    await _next_step(db, ctx, started.id)
    await _round(db, ctx, agent, started.id, "ROUND_BAD")
    with pytest.raises(BadRequestError, match="only 4 test questions") as refused:
        await _next_step(db, ctx, started.id)
    assert refused.value.details == {"missing_holdout": 1}
    stopped = await service.read(ctx, agent.id, started.id)
    assert (stopped.status, stopped.iteration, len(stopped.iterations)) == ("stopped", 1, 1)


async def test_an_attempt_that_still_draws_too_few_to_measure_is_not_checked(db):
    ctx, agent, _ = await _setup(db)
    dataset, measured = await _marked_dataset(db, ctx, share=Decimal("0.625"))
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(100), max_iterations=3),
    )
    for _ in range(2):
        await service.advance(started.id, ctx.organization_id)
    await _next_step(db, ctx, started.id)
    await _round(db, ctx, agent, started.id, "ROUND_BAD")
    with patch("app.services.improvement_pipeline.drawn_holdout", return_value=measured[:4]):
        drawn = await _next_step(db, ctx, started.id)
    assert drawn.iterations[1].held_out == 4
    with pytest.raises(BadRequestError, match="Add 1 more") as refused:
        await _round(db, ctx, agent, started.id, "ROUND_GOOD")
    assert refused.value.details == {"missing_holdout": 1}
    waiting = await service.read(ctx, agent.id, started.id)
    assert (waiting.status, waiting.stage, waiting.iteration) == ("waiting", "filtering", 2)
    assert not waiting.iterations[1].eval_run_ids
    blocked = NextStepBlocked(reason="missing_holdout", needed=1)
    assert waiting.next_step_blocked == blocked
    [listed] = await service.awaiting(ctx)
    assert listed.next_step_blocked == blocked
    notices = list(
        await db.scalars(
            select(Notification)
            .where(Notification.event_type == "improvement_finished")
            .order_by(Notification.created_at)
        )
    )
    assert notices[-1].render_context["next_step_blocked"] == {
        "reason": "missing_holdout",
        "needed": 1,
    }
    assert "1 more are needed" in notices[-1].summary


async def test_attribution_needs_consent_to_the_current_price_and_is_idempotent(db):
    ctx, agent, started, _, _ = await _two_rounds(db)
    service = ImprovementPipelineService(db)
    quote = await service.estimate_attribution(ctx, agent.id, started.id, 2)
    assert quote.changes == 1 and quote.total_usd > 0 and quote.affordable
    before = list(await db.scalars(select(EvalRun.id)))
    with pytest.raises(ConcurrentChangeError, match="estimate changed"):
        await service.start_attribution(
            ctx,
            agent.id,
            started.id,
            2,
            AttributionConsent(confirmed=True, estimate_usd=Decimal(0)),
        )
    assert list(await db.scalars(select(EvalRun.id))) == before
    result = await service.start_attribution(
        ctx,
        agent.id,
        started.id,
        2,
        AttributionConsent(confirmed=True, estimate_usd=quote.total_usd),
    )
    ids = result.iterations[1].attribution_eval_run_ids
    assert len(ids) == 1
    repeated = await service.start_attribution(
        ctx,
        agent.id,
        started.id,
        2,
        AttributionConsent(confirmed=True, estimate_usd=quote.total_usd),
    )
    assert repeated.iterations[1].attribution_eval_run_ids == ids
    assert len(list(await db.scalars(select(EvalRun.id)))) == len(before) + 1
    assert (await service.estimate_attribution(ctx, agent.id, started.id, 2)).already_started


@pytest.mark.security
async def test_the_next_round_cannot_start_when_its_whole_forecast_exceeds_budget(db):
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=5)
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(100), max_iterations=3),
    )
    for _ in range(2):
        await service.advance(started.id, ctx.organization_id)
    await _next_step(db, ctx, started.id)
    await _round(db, ctx, agent, started.id, "ROUND_BAD", exhaust_budget=True)
    stopped = await service.read(ctx, agent.id, started.id)
    assert (stopped.status, stopped.stop_reason) == ("stopped", "regression")
    quote = await service.estimate_continuation(
        ctx, agent.id, started.id, ImprovementContinue(budget_usd=stopped.budget_usd)
    )
    assert quote.mode == "next_round" and not quote.affordable
    with pytest.raises(PaymentRequiredError):
        await service.continue_run(
            ctx,
            agent.id,
            started.id,
            ContinuationConsent(
                confirmed=True,
                budget_usd=quote.budget_usd,
                estimate_usd=quote.total_usd,
                candidate_hash=quote.candidate_hash,
            ),
        )
    stopped = await service.read(ctx, agent.id, started.id)
    assert stopped.iteration == 1 and len(stopped.iterations) == 1


async def test_try_again_is_refused_before_it_costs_anything_when_too_few_questions_measure_it(
    db,
):
    ctx, agent, _ = await _setup(db)
    dataset = await _dataset(db, ctx, cases=5)
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(100), max_iterations=3),
    )
    for _ in range(2):
        await service.advance(started.id, ctx.organization_id)
    await _next_step(db, ctx, started.id)
    await _round(db, ctx, agent, started.id, "ROUND_BAD")
    stopped = await service.read(ctx, agent.id, started.id)
    assert stopped.status == "stopped"
    stored = await db.get(Dataset, dataset.id)
    assert stored is not None
    stored.improvement_holdout_share = Decimal("0.5")
    await db.flush()

    # Five questions keep three aside per attempt, short of the five a result needs.
    with pytest.raises(BadRequestError, match="only 3 test questions") as refused:
        await service.estimate_continuation(
            ctx, agent.id, started.id, ImprovementContinue(budget_usd=stopped.budget_usd)
        )

    assert refused.value.details == {"missing_holdout": 2}
    after = await service.read(ctx, agent.id, started.id)
    assert (after.iteration, len(after.iterations), after.spent_usd) == (
        1,
        1,
        stopped.spent_usd,
    )
    from app.schemas.improvement import ImprovementDiscard

    ended = await service.discard(ctx, agent.id, started.id, ImprovementDiscard(confirmed=True))
    assert ended.status == "rejected"


@pytest.mark.parametrize(
    ("markers", "maximum", "reason"),
    [
        (["ROUND_BAD", "ROUND_BAD"], 3, "repeat_candidate"),
        (["NEUTRAL_ONE", "NEUTRAL_TWO"], 3, "no_change"),
        (["ROUND_BAD_ONE", "ROUND_BAD_TWO"], 2, "regression"),
    ],
)
async def test_attempts_a_person_asks_for_never_overwrite_their_batch(db, markers, maximum, reason):
    from tests.integration.test_authoring import _improve

    ctx, agent, _ = await _setup(db)
    await _improve(db, ctx, agent, Improver(db))
    personal = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert personal is not None
    dataset = await _dataset(db, ctx, cases=5)
    service = ImprovementPipelineService(db)
    started = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=dataset.id, budget_usd=Decimal(100), max_iterations=maximum),
    )
    for _ in range(2):
        await service.advance(started.id, ctx.organization_id)
    await _next_step(db, ctx, started.id)
    for number, marker in enumerate(markers, start=1):
        if number > 1:
            await _next_step(db, ctx, started.id)
        await _round(db, ctx, agent, started.id, marker)
    stopped = await service.read(ctx, agent.id, started.id)
    assert stopped.status == "stopped" and stopped.stop_reason == reason
    assert stopped.round_hint == ("no_change" if reason == "no_change" else None)
    if stopped.iteration == maximum:
        with pytest.raises(BadRequestError, match="attempt limit"):
            await service.estimate_continuation(
                ctx, agent.id, started.id, ImprovementContinue(budget_usd=stopped.budget_usd)
            )
    current = await authoring_repo.get_open_batch(
        db, organization_id=ctx.organization_id, agent_id=agent.id
    )
    assert current is not None and current.id == personal.id
    if reason == "repeat_candidate":
        assert not stopped.iterations[1].eval_run_ids


@pytest.mark.security
async def test_attribution_refuses_a_changed_base_and_an_exhausted_session_budget(db):
    ctx, agent, started, _, _ = await _two_rounds(db)
    service = ImprovementPipelineService(db)
    quote = await service.estimate_attribution(ctx, agent.id, started.id, 2)
    row = await db.get(ImprovementRun, started.id)
    assert row is not None
    row.budget_usd = (await service.read(ctx, agent.id, started.id)).spent_usd
    await db.flush()
    assert not (await service.estimate_attribution(ctx, agent.id, started.id, 2)).affordable
    with pytest.raises(PaymentRequiredError):
        await service.start_attribution(
            ctx,
            agent.id,
            started.id,
            2,
            AttributionConsent(confirmed=True, estimate_usd=quote.total_usd),
        )
    agent.draft_spec = {**agent.draft_spec, "instructions": "Changed manually"}
    await db.flush()
    with pytest.raises(ConcurrentChangeError, match="stale"):
        await service.select_round(ctx, agent.id, started.id, 1)
    with pytest.raises(ConcurrentChangeError, match="stale"):
        await service.estimate_attribution(ctx, agent.id, started.id, 2)
