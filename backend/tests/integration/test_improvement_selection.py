"""Only the human-selected, measured changes reach an acceptance decision."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, ConcurrentChangeError, PaymentRequiredError
from app.db.models.authoring import AuthoringRequest
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.db.models.skill import Skill
from app.repositories import authoring_repo, improvement_repo
from app.schemas.improvement import (
    AttributionConsent,
    ImprovementFinish,
    ImprovementSelection,
    SelectionConsent,
)
from app.services.agent_runner import AgentRunnerService
from app.services.eval_run_worker import EvalRunWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _sessions
from tests.integration.test_improvement_pipeline import Answers, _ready_proposal
from tests.integration.test_improvement_rounds import RoundAnswers, _two_rounds

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _hunks(db, ctx, ready, number=1):
    return await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=ready.iterations[number - 1].batch_id
    )


async def _consent(service, ctx, agent, ready, ids, number=1):
    selected = ImprovementSelection(hunk_ids=ids)
    quote = await service.estimate_selection(ctx, agent.id, ready.id, number, selected)
    return SelectionConsent(
        hunk_ids=ids,
        confirmed=True,
        estimate_usd=quote.total_usd,
        candidate_hash=quote.candidate_hash,
    )


async def _finish_check(db, ctx, agent, ready, model=None):
    service = ImprovementPipelineService(db)
    await service.advance(ready.id, ctx.organization_id)
    active = await service.read(ctx, agent.id, ready.id)
    current = next(item for item in active.iterations if item.number == active.iteration)
    model = model or Answers(db)

    async def execute(runner, *args, **kwargs):
        assert not kwargs["candidate"].skill_bodies
        return await model.execute(runner, *args, **kwargs)

    with (
        patch.object(AgentRunnerService, "execute", new=execute),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            current.eval_run_ids[-1], ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    await service.advance(ready.id, ctx.organization_id)
    await service.advance(ready.id, ctx.organization_id)
    return await service.read(ctx, agent.id, ready.id)


async def test_only_selected_changes_are_checked_and_accepted_without_dismissing_the_rest(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    hunks = await _hunks(db, ctx, ready)
    instructions = next(h for h in hunks if h.kind == "instructions")
    excluded = await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=ready.iterations[0].batch_id,
        hunks=[
            {
                "kind": "create_skill",
                "origin": "improve",
                "new_value": {
                    "name": "unselected-procedure",
                    "description": "A procedure not selected",
                    "content": "Do not include this procedure in the selected check.",
                },
            }
        ],
    )
    consent = await _consent(service, ctx, agent, ready, [instructions.id])
    old = list(ready.iterations[0].eval_run_ids)
    queued = await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    assert queued.status == "running" and queued.iterations[0].included_hunk_ids == [
        instructions.id
    ]
    assert queued.iterations[0].previous_eval_run_ids == old
    assert (await service.check_selection(ctx, agent.id, ready.id, 1, consent)).id == ready.id
    assert all(h.status == "pending" for h in [*hunks, *excluded])
    checked = await _finish_check(db, ctx, agent, ready)
    assert checked.status == "ready" and checked.iterations[0].verdict == "better"
    assert checked.spent_usd > ready.spent_usd
    original_tools = AgentSpec.model_validate(agent.draft_spec).capabilities
    result = await service.finish(
        ctx,
        agent.id,
        ready.id,
        ImprovementFinish(confirmed=True, publish=False, automatic_check=False),
    )
    assert result.session.status == "accepted"
    assert "30 days" in AgentSpec.model_validate(agent.draft_spec).instructions
    assert AgentSpec.model_validate(agent.draft_spec).capabilities == original_tools
    assert AgentSpec.model_validate(agent.draft_spec).skill_ids == []
    assert excluded[0].status == "pending"
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0
    assert all(h.status == "pending" for h in hunks if h.id != instructions.id)
    await service.advance(ready.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, ready.id)).status == "accepted"


async def test_an_unchanged_manual_selection_stops_without_another_paid_proposal(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    tool = next(h for h in await _hunks(db, ctx, ready) if h.kind == "tool_override")
    consent = await _consent(service, ctx, agent, ready, [tool.id])
    before = await db.scalar(select(func.count()).select_from(AuthoringRequest))
    await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    checked = await _finish_check(db, ctx, agent, ready)
    assert checked.status == "stopped" and checked.stop_reason == "no_change"
    assert len(checked.iterations) == 1
    assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == before
    assert "30 days" not in AgentSpec.model_validate(agent.draft_spec).instructions


async def test_quote_refuses_changed_choices_and_invalid_round_members_before_paid_work(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    hunks = await _hunks(db, ctx, ready)
    consent = await _consent(service, ctx, agent, ready, [hunks[0].id])
    before = await db.scalar(select(func.count()).select_from(EvalRun))
    with pytest.raises(ConcurrentChangeError, match="estimate changed"):
        await service.check_selection(
            ctx, agent.id, ready.id, 1, consent.model_copy(update={"candidate_hash": "0" * 64})
        )
    with pytest.raises(ConcurrentChangeError, match="estimate changed"):
        await service.check_selection(
            ctx, agent.id, ready.id, 1, consent.model_copy(update={"estimate_usd": Decimal(0)})
        )
    with pytest.raises(BadRequestError, match="pending changes"):
        await service.estimate_selection(
            ctx, agent.id, ready.id, 1, ImprovementSelection(hunk_ids=[uuid4()])
        )
    assert await db.scalar(select(func.count()).select_from(EvalRun)) == before
    assert (await service.read(ctx, agent.id, ready.id)).status == "ready"


@pytest.mark.security
async def test_budget_and_a_running_child_prevent_reserving_a_selected_check(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    hunk = (await _hunks(db, ctx, ready))[0]
    quote = await service.estimate_attribution(ctx, agent.id, ready.id, 1)
    await service.start_attribution(
        ctx, agent.id, ready.id, 1, AttributionConsent(confirmed=True, estimate_usd=quote.total_usd)
    )
    consent = await _consent(service, ctx, agent, ready, [hunk.id])
    with pytest.raises(ConcurrentChangeError, match="current checks"):
        await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    await service._stop_children(await db.get(ImprovementRun, ready.id))
    row = await db.get(ImprovementRun, ready.id)
    row.budget_usd = ready.spent_usd
    await db.flush()
    consent = await _consent(service, ctx, agent, ready, [hunk.id])
    with pytest.raises(PaymentRequiredError, match="remaining budget"):
        await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    assert (await service.read(ctx, agent.id, ready.id)).iterations[
        0
    ].included_hunk_ids == ready.iterations[0].included_hunk_ids


async def test_rechecking_an_earlier_round_keeps_later_costs_and_best_result(db):
    ctx, agent, started, _, _ = await _two_rounds(db)
    service = ImprovementPipelineService(db)
    ready = await service.read(ctx, agent.id, started.id)
    later_cost = ready.iterations[1].cost_usd
    hunk = (await _hunks(db, ctx, ready))[0]
    consent = await _consent(service, ctx, agent, ready, [hunk.id])
    await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    checked = await _finish_check(db, ctx, agent, ready, RoundAnswers(db))
    assert checked.status == "stopped" and checked.stop_reason == "regression"
    assert checked.best_iteration_id == ready.iterations[1].id
    assert checked.iterations[1].cost_usd == later_cost
    assert sum(item.cost_usd for item in checked.iterations) == checked.spent_usd
    assert len(checked.iterations) == 2


async def test_edited_suggestions_cannot_reuse_attribution_or_be_selected_as_measured(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    hunk = next(h for h in await _hunks(db, ctx, ready) if h.kind == "instructions")
    hunk.new_text += " Explain the deadline."
    await db.flush()
    with pytest.raises(ConcurrentChangeError, match="differ from the measured"):
        await service.estimate_attribution(ctx, agent.id, ready.id, 1)
    with pytest.raises(ConcurrentChangeError, match="differ from the measured"):
        await service.select_round(ctx, agent.id, ready.id, 1)
    consent = await _consent(service, ctx, agent, ready, [hunk.id])
    await service.check_selection(ctx, agent.id, ready.id, 1, consent)
    assert (await _finish_check(db, ctx, agent, ready)).status == "ready"


def test_selection_requires_distinct_nonempty_changes_and_explicit_confirmation():
    key = uuid4()
    for ids in ([], [key, key]):
        with pytest.raises(ValidationError):
            ImprovementSelection(hunk_ids=ids)
    with pytest.raises(ValidationError):
        SelectionConsent(
            hunk_ids=[key], confirmed=False, estimate_usd=Decimal(0), candidate_hash="a" * 64
        )


async def test_later_suggestions_are_not_silently_included_in_the_measured_candidate(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    measured = ready.iterations[0].included_hunk_ids
    assert measured and len(measured) == len(await _hunks(db, ctx, ready))
    [later] = await authoring_repo.add_hunks(
        db,
        organization_id=ctx.organization_id,
        batch_id=ready.iterations[0].batch_id,
        hunks=[
            {
                "kind": "instructions",
                "origin": "verify",
                "old_text": "Be brief.",
                "new_text": "Be very verbose.",
            }
        ],
    )
    assert later.id not in measured
    assert (
        await improvement_repo.measured_hunks(
            db, organization_id=uuid4(), batch_id=ready.iterations[0].batch_id
        )
        is None
    )
    result = await service.finish(
        ctx,
        agent.id,
        ready.id,
        ImprovementFinish(confirmed=True, publish=False, automatic_check=False),
    )
    assert result.session.status == "accepted"
    assert "30 days" in AgentSpec.model_validate(agent.draft_spec).instructions
    assert "verbose" not in AgentSpec.model_validate(agent.draft_spec).instructions
    assert later.status == "pending"
