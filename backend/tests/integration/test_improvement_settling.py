"""A session ends where a person leaves it, and says so at every end.

An equal later round and its own exposures decide nothing; every end - ready,
stopped, stale, cancelled by somebody else, decided outside the wizard, a check
of a finished session - reaches its requester once, and open pages hear of it.
"""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.authoring import BatchStatus
from app.db.models.eval_run import EvalRun
from app.db.models.improvement import ImprovementRun
from app.db.models.notification import Notification
from app.repositories import authoring_repo, improvement_repo
from app.schemas.improvement import ImprovementFinish
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.notifications import NotificationService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _member
from tests.integration.test_improvement_pipeline import _ready_proposal, _started

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _equal_second_round(db, ctx, agent, ready):
    """Round 2 as judging finds it after Improve again: its own batch, measured as well as round 1."""
    org = ctx.organization_id
    run = await db.get(ImprovementRun, ready.id)
    [first] = await improvement_repo.list_iterations(db, organization_id=org, run_id=run.id)
    batch = await authoring_repo.create_batch(
        db,
        organization_id=org,
        agent_id=agent.id,
        request_id=None,
        source_started_at=datetime.now(UTC),
        expected_effect="round two",
        evidence_conversation_ids=[],
        improvement_run_id=run.id,
    )
    second = await improvement_repo.create_iteration(
        db, organization_id=org, run_id=run.id, number=2
    )
    await improvement_repo.update_iteration(
        db,
        iteration=second,
        values={
            "batch_id": batch.id,
            "eval_run_ids": list(first.eval_run_ids),
            "candidate_spec_hash": first.candidate_spec_hash,
            "included_hunk_ids": [],
        },
    )
    run.max_iterations, run.iteration, run.status, run.stage = 3, 2, "running", "judging"
    await db.flush()
    return run, first, second, batch


async def test_an_equal_second_round_leaves_the_best_round_waiting_and_acceptable(db):
    ctx, agent, ready = await _ready_proposal(db)
    run, first, _, second_batch = await _equal_second_round(db, ctx, agent, ready)
    service = ImprovementPipelineService(db)

    await service.advance(run.id, ctx.organization_id)
    judged = await service.read(ctx, agent.id, run.id)
    assert (judged.status, judged.best_iteration_id) == ("ready", first.id)
    batch = await authoring_repo.get_batch(db, first.batch_id, organization_id=ctx.organization_id)
    assert batch.status == "open" and second_batch.status != "open"

    await service.advance(run.id, ctx.organization_id)
    assert (await service.read(ctx, agent.id, run.id)).status == "ready"
    finished = await service.finish(
        ctx, agent.id, run.id, ImprovementFinish(confirmed=True, publish=True)
    )
    assert finished.session.status == "published"


async def test_a_batch_its_own_session_superseded_is_not_a_rejection(db):
    ctx, agent, ready = await _ready_proposal(db)
    run, first, second, second_batch = await _equal_second_round(db, ctx, agent, ready)
    first_batch = await authoring_repo.get_batch(
        db, first.batch_id, organization_id=ctx.organization_id
    )
    await authoring_repo.close_batch(db, batch=first_batch, status=BatchStatus.SUPERSEDED)
    second_batch.status = "open"
    run.status, run.stage, run.best_iteration_id = "ready", "judging", first.id
    await db.flush()

    await ImprovementPipelineService(db).advance(run.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, run.id)).status == "ready"

    second_batch.improvement_run_id = None
    await db.flush()
    await ImprovementPipelineService(db).advance(run.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, run.id)).status == "rejected"


async def _ends(db, run_id, *, waits: bool = False) -> list[tuple[str, str | None]]:
    """What the session's requester was told, in order: its ends, or with `waits` its stops."""
    rows = await db.scalars(
        select(Notification)
        .where(Notification.event_type == "improvement_finished")
        .order_by(Notification.created_at)
    )
    return [
        (row.render_context["status"], row.render_context["reason"])
        for row in rows
        if str(run_id) in row.occurrence_id and (row.render_context["status"] == "waiting") == waits
    ]


async def test_each_end_of_a_session_reaches_its_requester_once(db):
    ctx, agent, ready = await _ready_proposal(db)
    assert await _ends(db, ready.id) == [("ready", None)]
    assert await _ends(db, ready.id, waits=True) == [
        ("waiting", "analyzing"),
        ("waiting", "filtering"),
    ]
    run, *_ = await _equal_second_round(db, ctx, agent, ready)

    await ImprovementPipelineService(db).advance(run.id, ctx.organization_id)
    assert await _ends(db, ready.id) == [("ready", None), ("ready", None)]

    service = NotificationService(db)
    for _ in range(2):
        await service.improvement_finished(
            agent=agent,
            run_id=run.id,
            user_id=ctx.user_id,
            status="stopped",
            reason="budget",
            end="the same end",
        )
    assert len(await _ends(db, ready.id)) == 3


async def test_a_stale_session_and_one_stopped_by_an_administrator_are_announced(db):
    from app.core.permissions import OrgRoleName

    ctx, agent, _, stale = await _started(db)
    agent.draft_spec = {**agent.draft_spec, "instructions": "A newer manual decision"}
    await db.flush()
    await ImprovementPipelineService(db).advance(stale.id, ctx.organization_id)
    assert await _ends(db, stale.id) == [("stale", "stale")]

    run = await db.get(ImprovementRun, stale.id)
    run.status, run.stop_reason, run.finished_at = "running", None, None
    await db.flush()
    await ImprovementPipelineService(db).cancel(ctx, agent.id, stale.id)
    assert len(await _ends(db, stale.id)) == 1

    run.status = "running"
    await db.flush()
    admin = await _member(db, ctx, OrgRoleName.ADMIN)
    await ImprovementPipelineService(db).cancel(admin, agent.id, stale.id)
    assert (await _ends(db, stale.id))[-1] == ("cancelled", None)


async def test_a_decision_made_outside_the_wizard_ends_the_session_and_is_announced(db):
    from app.schemas.authoring import HunkDecision
    from app.services.authoring import AuthoringService

    ctx, agent, ready = await _ready_proposal(db)
    batch = await authoring_repo.get_batch(
        db, ready.iterations[0].batch_id, organization_id=ctx.organization_id
    )
    hunks = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=batch.id
    )
    for hunk in hunks:
        await AuthoringService(db).decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    with patch("app.services.improvement_pipeline.spawn_after_commit") as announced:
        await ImprovementPipelineService(db).advance(ready.id, ctx.organization_id)
    assert (await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)).status == (
        "accepted"
    )
    assert announced.call_count == 1
    assert (await _ends(db, ready.id))[-1] == ("accepted", None)


async def test_finishing_tells_the_agents_other_open_pages(db):
    ctx, agent, ready = await _ready_proposal(db)
    with patch("app.services.improvement_pipeline.spawn_after_commit") as announced:
        await ImprovementPipelineService(db).finish(
            ctx, agent.id, ready.id, ImprovementFinish(confirmed=True)
        )
    assert [call.kwargs["name"] for call in announced.call_args_list] == [
        f"improvement-moved:{ready.id}"
    ]


async def test_a_knowledge_or_attribution_check_of_a_finished_session_is_announced(db):
    ctx, agent, ready = await _ready_proposal(db)
    org = ctx.organization_id

    def check(**proposal) -> EvalRun:
        return EvalRun(
            id=uuid4(),
            organization_id=org,
            agent_id=agent.id,
            status="completed",
            purpose="gate",
            created_by_user_id=ctx.user_id,
            proposal_check={"improvement_run_id": str(ready.id), **proposal},
        )

    service = ImprovementPipelineService(db)
    knowledge = check(knowledge={"topic_id": str(uuid4())})
    await service.check_finished(knowledge)
    attribution = check()
    [round_one] = await improvement_repo.list_iterations(db, organization_id=org, run_id=ready.id)
    await improvement_repo.update_iteration(
        db,
        iteration=round_one,
        values={"attribution_eval_run_ids": {str(uuid4()): str(attribution.id)}},
    )
    await service.check_finished(attribution)
    await service.check_finished(check())
    assert (await _ends(db, ready.id))[1:] == [
        ("ready", "knowledge_check"),
        ("ready", "attribution_check"),
    ]

    gone = check()
    gone.proposal_check = {"improvement_run_id": str(uuid4())}
    await service.check_finished(gone)
    assert len(await _ends(db, ready.id)) == 3


async def test_a_later_round_reads_every_example_when_nothing_was_classified(db):
    ctx, _, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    run = await db.get(ImprovementRun, ready.id)
    [round_one] = await improvement_repo.list_iterations(
        db, organization_id=ctx.organization_id, run_id=run.id
    )
    assert round_one.classify_job_id is None

    excluded = await service._knowledge_exclusions(ctx, run)
    pack = await service.authoring.evidence.for_improvement(
        ctx, run.id, excluded_message_ids=excluded
    )
    assert excluded == []
    assert set(run.chat_evidence_run_ids) <= {item.run_id for item in pack.runs}


async def test_a_status_write_outside_the_state_table_is_refused_as_a_conflict(db):
    from app.core.exceptions import ConcurrentChangeError
    from app.db.models.improvement import ImprovementStage, ImprovementStatus
    from app.services import improvement_states as rules

    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    await service.finish(ctx, agent.id, ready.id, ImprovementFinish(confirmed=True, publish=True))
    run = await db.get(ImprovementRun, ready.id)

    with pytest.raises(ConcurrentChangeError) as refused:
        await service._move(
            run, rules.Transition(ImprovementStatus.RUNNING, ImprovementStage.PROPOSING)
        )
    assert refused.value.details == {"status": "published", "to": "running"}
    assert run.status == "published"


async def test_a_kept_draft_takes_no_more_decisions_in_its_session(db):
    """Keeping the draft ends the session: it is published with the agent's own Publish."""
    from app.core.exceptions import ConcurrentChangeError

    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    await service.finish(ctx, agent.id, ready.id, ImprovementFinish(confirmed=True))

    with pytest.raises(ConcurrentChangeError, match="finished") as refused:
        await service.finish(
            ctx, agent.id, ready.id, ImprovementFinish(confirmed=True, publish=True)
        )
    assert refused.value.details == {"status": "accepted"}
    assert (await service.read(ctx, agent.id, ready.id)).status == "accepted"


@pytest.mark.parametrize("edited", [False, True])
async def test_a_kept_draft_published_elsewhere_names_its_version_when_it_was_measured(db, edited):
    from app.core.exceptions import ConcurrentChangeError
    from app.services.agent_registry import AgentRegistryService

    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    await service.finish(ctx, agent.id, ready.id, ImprovementFinish(confirmed=True))
    if edited:
        agent.draft_spec = {**agent.draft_spec, "instructions": "Other."}
        await db.flush()
    version = await AgentRegistryService(db).publish(ctx, agent.id)
    with pytest.raises(ConcurrentChangeError, match="finished"):
        await service.finish(
            ctx, agent.id, ready.id, ImprovementFinish(confirmed=True, publish=True)
        )

    await service.advance(ready.id, ctx.organization_id)
    settled = await service.read(ctx, agent.id, ready.id)
    assert settled.status == "published"
    assert settled.published_version == (None if edited else version.version)


@pytest.mark.security
async def test_only_the_requester_spends_the_session_on_attribution_or_a_knowledge_check(db):
    from decimal import Decimal

    from app.core.exceptions import AuthorizationError
    from app.core.permissions import OrgRoleName
    from app.schemas.improvement import AttributionConsent, KnowledgeCheckConsent

    ctx, agent, ready = await _ready_proposal(db)
    editor = await _member(db, ctx, OrgRoleName.ADMIN)
    service = ImprovementPipelineService(db)
    spent = (await service.read(ctx, agent.id, ready.id)).spent_usd

    with pytest.raises(AuthorizationError, match="requester"):
        await service.start_attribution(
            editor,
            agent.id,
            ready.id,
            1,
            AttributionConsent(confirmed=True, estimate_usd=Decimal("1")),
        )
    with pytest.raises(AuthorizationError, match="requester"):
        await service.start_knowledge(
            editor,
            agent.id,
            ready.id,
            KnowledgeCheckConsent(
                topic_id=uuid4(),
                round=1,
                case_ids=[uuid4()],
                confirmed=True,
                estimate_usd=Decimal("1"),
                draft_hash="a" * 64,
            ),
        )
    after = await service.read(ctx, agent.id, ready.id)
    assert after.spent_usd == spent
    assert after.iterations[0].attribution_eval_run_ids == {}


async def test_the_timeline_names_who_decided_what_and_only_to_those_who_see_members(db):
    from dataclasses import replace

    from app.core.permissions import Perm
    from app.schemas.improvement import ImprovementDiscard

    ctx, agent, ready = await _ready_proposal(db)
    service = ImprovementPipelineService(db)
    own_steps = (await service.read(ctx, agent.id, ready.id)).timeline
    assert all(
        event.actor_user_id is None
        for event in own_steps
        if event.action == "improvement.stage_changed"
    )

    await service.discard(ctx, agent.id, ready.id, ImprovementDiscard(confirmed=True))
    timeline = (await service.read(ctx, agent.id, ready.id)).timeline
    by_person = [event for event in timeline if event.action == "improvement.discarded"]
    assert {(event.actor_user_id, event.actor_name is not None) for event in by_person} == {
        (ctx.user_id, True)
    }

    outsider = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW}))
    hidden = (await service.read(outsider, agent.id, ready.id)).timeline
    assert {
        (event.actor_user_id, event.actor_name)
        for event in hidden
        if event.action == "improvement.discarded"
    } == {(ctx.user_id, None)}


async def test_a_publish_that_took_none_of_the_suggestions_rejects_them(db):
    from app.services.agent_registry import AgentRegistryService

    ctx, agent, ready = await _ready_proposal(db)
    await AgentRegistryService(db).publish(ctx, agent.id)
    await ImprovementPipelineService(db).advance(ready.id, ctx.organization_id)
    settled = await ImprovementPipelineService(db).read(ctx, agent.id, ready.id)
    assert (settled.status, settled.published_version) == ("rejected", None)
