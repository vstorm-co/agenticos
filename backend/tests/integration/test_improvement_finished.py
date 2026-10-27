"""A finished session is a record: nothing changes it, and it never stands in a new one's way.

Kept as a draft, published, discarded, cancelled or outdated, a session answers
every change with a conflict and is read as it ended. Repeating the decision that
ended it is answered as before, and the agent can start its next session at once.
"""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, ConcurrentChangeError, NotFoundError
from app.core.permissions import OrgRoleName
from app.db.models.improvement import ImprovementIteration, ImprovementRun
from app.schemas.improvement import (
    AttributionConsent,
    ContinuationConsent,
    ImprovementContinue,
    ImprovementDiscard,
    ImprovementFinish,
    ImprovementSelection,
    ImprovementStart,
    KnowledgeCheckTarget,
    SelectionConsent,
    TopicDeferral,
)
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _member
from tests.integration.test_improvement_pipeline import _ready_proposal

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]

CLOSED = ["accepted", "published", "rejected", "cancelled", "stale"]
CONSENT = {"confirmed": True, "estimate_usd": Decimal("1")}


def _changes(service: ImprovementPipelineService, ctx, agent_id, run_id):
    """Every change a person can ask of a session, by name."""
    hash_ = "a" * 64
    knowledge = KnowledgeCheckTarget(topic_id=uuid4(), round=1, case_ids=[uuid4()])
    return {
        "defer_topic": lambda: service.defer_topic(
            ctx, agent_id, run_id, uuid4(), TopicDeferral(later=True)
        ),
        "cancel": lambda: service.cancel(ctx, agent_id, run_id),
        "finish": lambda: service.finish(
            ctx, agent_id, run_id, ImprovementFinish(confirmed=True, publish=True)
        ),
        "retry": lambda: service.retry(ctx, agent_id, run_id),
        "estimate_continuation": lambda: service.estimate_continuation(
            ctx, agent_id, run_id, ImprovementContinue(budget_usd=Decimal("5"))
        ),
        "continue_run": lambda: service.continue_run(
            ctx,
            agent_id,
            run_id,
            ContinuationConsent(budget_usd=Decimal("5"), candidate_hash=hash_, **CONSENT),
        ),
        "discard": lambda: service.discard(
            ctx, agent_id, run_id, ImprovementDiscard(confirmed=True)
        ),
        "select_round": lambda: service.select_round(ctx, agent_id, run_id, 1),
        "estimate_knowledge": lambda: service.estimate_knowledge(ctx, agent_id, run_id, knowledge),
        "estimate_selection": lambda: service.estimate_selection(
            ctx, agent_id, run_id, 1, ImprovementSelection(hunk_ids=[uuid4()])
        ),
        "check_selection": lambda: service.check_selection(
            ctx,
            agent_id,
            run_id,
            1,
            SelectionConsent(hunk_ids=[uuid4()], candidate_hash=hash_, **CONSENT),
        ),
        "estimate_attribution": lambda: service.estimate_attribution(ctx, agent_id, run_id, 1),
        "start_attribution": lambda: service.start_attribution(
            ctx, agent_id, run_id, 1, AttributionConsent(**CONSENT)
        ),
    }


async def _ended(db, status: str):
    ctx, agent, ready = await _ready_proposal(db)
    run = await db.get(ImprovementRun, ready.id)
    assert run is not None
    run.status = status
    await db.flush()
    return ctx, agent, ready


@pytest.mark.parametrize("status", CLOSED)
async def test_a_finished_session_refuses_every_change_as_a_conflict(db, status):
    ctx, agent, ready = await _ended(db, status)
    service = ImprovementPipelineService(db)
    repeats = {"cancelled": "cancel", "rejected": "discard"}
    for name, change in _changes(service, ctx, agent.id, ready.id).items():
        if repeats.get(status) == name:
            continue
        with pytest.raises(ConcurrentChangeError, match="finished") as refused:
            await change()
        assert refused.value.details == {"status": status}, name
    assert (await service.read(ctx, agent.id, ready.id)).status == status


@pytest.mark.parametrize(("status", "action"), [("cancelled", "cancel"), ("rejected", "discard")])
async def test_repeating_the_decision_that_ended_it_answers_as_before(db, status, action):
    ctx, agent, ready = await _ended(db, status)
    service = ImprovementPipelineService(db)
    again = await _changes(service, ctx, agent.id, ready.id)[action]()
    assert again.status == status


async def test_a_session_kept_as_a_draft_leaves_the_agent_free_for_its_next_one(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    await service.finish(ctx, agent.id, ready.id, ImprovementFinish(confirmed=True))
    kept = await service.read(ctx, agent.id, ready.id)

    following = await service.start(
        ctx,
        agent.id,
        ImprovementStart(dataset_id=kept.dataset_id, max_iterations=1, budget_usd=Decimal("20")),
    )

    assert following.status == "queued" and following.id != kept.id
    assert (await service.read(ctx, agent.id, ready.id)).status == "accepted"


async def test_the_changes_a_session_measured_read_as_they_were_decided(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    await service.finish(ctx, agent.id, ready.id, ImprovementFinish(confirmed=True))
    chosen = next(r for r in ready.iterations if r.id == ready.best_iteration_id)

    changes = await service.changes(ctx, agent.id, ready.id)

    assert changes, "the chosen round measured changes"
    assert {change.id for change in changes} <= set(
        chosen.included_hunk_ids or [change.id for change in changes]
    )
    assert {change.status for change in changes} == {"accepted"}


async def test_every_change_an_attempt_proposed_reads_without_a_chosen_round(db):
    ctx, agent, ready = await _ready_proposal(db)
    run = await db.get(ImprovementRun, ready.id)
    assert run is not None
    run.best_iteration_id = None
    await db.flush()
    service = ImprovementPipelineService(db)
    proposed = ready.iterations[0]

    changes = await service.changes(ctx, agent.id, ready.id, attempt=proposed.number)

    assert changes and {change.id for change in changes} >= set(proposed.included_hunk_ids or [])
    assert await service.changes(ctx, agent.id, ready.id, attempt=99) == []


async def test_a_session_with_no_kept_attempt_shows_the_attempt_in_hand(db):
    ctx, agent, ready = await _ready_proposal(db)
    run = await db.get(ImprovementRun, ready.id)
    assert run is not None
    run.best_iteration_id = None
    await db.flush()
    service = ImprovementPipelineService(db)
    in_hand = await service.changes(ctx, agent.id, ready.id, attempt=run.iteration)
    included = set(ready.iterations[0].included_hunk_ids or [change.id for change in in_hand])

    shown = await service.changes(ctx, agent.id, ready.id)

    assert shown and {change.id for change in shown} == included


async def test_an_attempt_in_hand_that_wrote_nothing_shows_no_changes(db):
    ctx, agent, ready = await _ready_proposal(db)
    run = await db.get(ImprovementRun, ready.id)
    assert run is not None
    run.best_iteration_id = None
    in_hand = await db.get(ImprovementIteration, ready.iterations[0].id)
    assert in_hand is not None and in_hand.number == run.iteration
    in_hand.batch_id = None
    await db.flush()

    assert await ImprovementPipelineService(db).changes(ctx, agent.id, ready.id) == []


@pytest.mark.security
async def test_a_reader_of_runs_sees_a_sessions_changes_and_nobody_else_does(db):
    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    # An operator reads agents and runs without editing either: the history's reader.
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    viewer = await _member(db, ctx, OrgRoleName.VIEWER)
    elsewhere = replace(ctx, organization_id=uuid4())

    assert [c.id for c in await service.changes(operator, agent.id, ready.id)] == [
        c.id for c in await service.changes(ctx, agent.id, ready.id)
    ]
    with pytest.raises(AuthorizationError, match="runs:view"):
        await service.changes(viewer, agent.id, ready.id)
    with pytest.raises(NotFoundError):
        await service.changes(elsewhere, agent.id, ready.id)
    with pytest.raises(NotFoundError, match="session"):
        await service.changes(ctx, agent.id, uuid4())
