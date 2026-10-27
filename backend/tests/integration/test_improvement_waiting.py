"""A session waits for a person after Understand and after Changes.

Each paid step after those is one somebody asked for, at a price they saw;
whoever may start a session on the agent may take it, and the session's
following steps run as them.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConcurrentChangeError, NotFoundError
from app.core.permissions import OrgRoleName
from app.db.models.authoring import AuthoringRequest
from app.db.models.improvement import ImprovementRun
from app.db.models.notification import Notification
from app.repositories import authoring_repo, improvement_repo
from app.schemas.authoring import AuthoringStart
from app.schemas.improvement import (
    ContinuationConsent,
    ImprovementContinue,
    ImprovementRead,
    ImprovementSelection,
    ImprovementTarget,
)
from app.services.authoring_worker import AuthoringWorker
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import Improver, _answering, _sessions
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import _member
from tests.integration.test_improvement_pipeline import _next_step, _started, _until_child

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _at_understand(db: AsyncSession):
    ctx, agent, _, read = await _started(db)
    for _ in range(3):
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    return ctx, agent, await ImprovementPipelineService(db).read(ctx, agent.id, read.id)


async def _at_changes(db: AsyncSession):
    ctx, agent, _, read = await _started(db)
    await _until_child(db, ctx, read.id)
    proposing = await ImprovementPipelineService(db).read(ctx, agent.id, read.id)
    request_id = proposing.iterations[0].authoring_request_id
    assert request_id is not None
    with _answering(Improver(db)):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    for _ in range(2):
        await ImprovementPipelineService(db).advance(read.id, ctx.organization_id)
    return ctx, agent, await ImprovementPipelineService(db).read(ctx, agent.id, read.id)


async def _consent(service, ctx, agent, session) -> ContinuationConsent:
    quote = await service.estimate_continuation(
        ctx, agent.id, session.id, ImprovementContinue(budget_usd=session.budget_usd)
    )
    return ContinuationConsent(
        confirmed=True,
        budget_usd=quote.budget_usd,
        estimate_usd=quote.total_usd,
        candidate_hash=quote.candidate_hash,
    )


async def _requests(db: AsyncSession, session: ImprovementRead) -> int:
    return len(
        (
            await db.scalars(
                select(AuthoringRequest).where(AuthoringRequest.improvement_run_id == session.id)
            )
        ).all()
    )


async def test_a_session_waits_after_understand_and_proposes_only_when_asked(db):
    ctx, agent, waiting = await _at_understand(db)
    assert (waiting.status, waiting.stage, waiting.next_step) == ("waiting", "analyzing", "propose")
    assert waiting.finished_at is None
    service = ImprovementPipelineService(db)
    # The start shows the split the analysis then records, from one calculation.
    started_with = await service.estimate(
        ctx, agent.id, ImprovementTarget(dataset_id=waiting.dataset_id, max_iterations=1)
    )
    assert started_with.held_out == waiting.iterations[0].held_out is not None
    await service.advance(waiting.id, ctx.organization_id)
    assert await service.sweep() == 0
    assert await _requests(db, waiting) == 0

    quote = await service.estimate_continuation(
        ctx, agent.id, waiting.id, ImprovementContinue(budget_usd=waiting.budget_usd)
    )
    proposal = await service.authoring.estimate_agent(
        ctx,
        agent.id,
        AuthoringStart(window_days=30),
        improvement_run_id=waiting.id,
    )
    assert (quote.mode, quote.total_usd, quote.expected_usd, quote.affordable) == (
        "next_step",
        proposal.estimate_usd,
        proposal.estimate_usd,
        True,
    )
    moved = await _next_step(db, ctx, waiting.id)
    assert (moved.status, moved.stage, moved.next_step) == ("running", "proposing", None)
    await service.advance(waiting.id, ctx.organization_id)
    assert await _requests(db, waiting) == 1


async def test_a_session_waits_after_changes_and_checks_only_what_a_person_chose(db):
    ctx, agent, waiting = await _at_changes(db)
    assert (waiting.status, waiting.stage, waiting.next_step) == ("waiting", "filtering", "check")
    assert waiting.finished_at is None and waiting.next_step_blocked is None
    service = ImprovementPipelineService(db)
    await service.advance(waiting.id, ctx.organization_id)
    assert not (await service.read(ctx, agent.id, waiting.id)).iterations[0].eval_run_ids
    hunks = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=waiting.iterations[0].batch_id
    )
    assert set(waiting.iterations[0].included_hunk_ids or []) == {h.id for h in hunks}
    everything = await service.estimate_continuation(
        ctx, agent.id, waiting.id, ImprovementContinue(budget_usd=waiting.budget_usd)
    )
    # The most a check may cost includes the repeat an inconclusive result gets.
    assert 0 < everything.expected_usd * 2 <= everything.total_usd

    chosen = await service.choose_changes(
        ctx, agent.id, waiting.id, ImprovementSelection(hunk_ids=[hunks[0].id])
    )
    assert chosen.iterations[0].included_hunk_ids == [hunks[0].id]
    assert chosen.iterations[0].candidate_spec_hash != waiting.iterations[0].candidate_spec_hash
    assert any(event.action == "improvement.changes_chosen" for event in chosen.timeline)
    stale_consent = ContinuationConsent(
        confirmed=True,
        budget_usd=everything.budget_usd,
        estimate_usd=everything.total_usd,
        candidate_hash=everything.candidate_hash,
    )
    with pytest.raises(ConcurrentChangeError, match="changed"):
        await service.continue_run(ctx, agent.id, waiting.id, stale_consent)

    consent = await _consent(service, ctx, agent, chosen)
    checking = await service.continue_run(ctx, agent.id, waiting.id, consent)
    assert (checking.status, checking.stage) == ("running", "evaluating")
    assert [change.id for change in await service.changes(ctx, agent.id, waiting.id)] == [
        hunks[0].id
    ]
    [check_id] = checking.iterations[0].eval_run_ids
    again = await service.continue_run(ctx, agent.id, waiting.id, consent)
    assert again.iterations[0].eval_run_ids == [check_id]
    with pytest.raises(BadRequestError, match="waits for its check"):
        await service.choose_changes(
            ctx, agent.id, waiting.id, ImprovementSelection(hunk_ids=[hunks[0].id])
        )


async def test_changes_are_chosen_only_among_the_attempts_pending_ones(db):
    ctx, agent, waiting = await _at_changes(db)
    service = ImprovementPipelineService(db)
    with pytest.raises(BadRequestError) as refused:
        await service.choose_changes(
            ctx, agent.id, waiting.id, ImprovementSelection(hunk_ids=[uuid4()])
        )
    assert refused.value.details == {
        "fields": [{"field": "hunk_ids", "message": "Choose among this attempt's pending changes"}]
    }
    viewer = await _member(db, ctx, OrgRoleName.VIEWER)
    hunks = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=waiting.iterations[0].batch_id
    )
    with pytest.raises(NotFoundError):
        await service.choose_changes(
            viewer, agent.id, waiting.id, ImprovementSelection(hunk_ids=[hunks[0].id])
        )


async def test_changes_an_earlier_attempt_checked_are_not_checked_again(db):
    ctx, agent, waiting = await _at_changes(db)
    earlier = await improvement_repo.create_iteration(
        db, organization_id=ctx.organization_id, run_id=waiting.id, number=2
    )
    await improvement_repo.update_iteration(
        db,
        iteration=earlier,
        values={
            "eval_run_ids": [uuid4()],
            "candidate_spec_hash": waiting.iterations[0].candidate_spec_hash,
        },
    )
    service = ImprovementPipelineService(db)
    with pytest.raises(BadRequestError, match="already checked"):
        await service.estimate_continuation(
            ctx, agent.id, waiting.id, ImprovementContinue(budget_usd=waiting.budget_usd)
        )


async def test_anyone_who_may_start_takes_the_next_step_and_the_session_runs_as_them(db):
    ctx, agent, waiting = await _at_understand(db)
    service = ImprovementPipelineService(db)
    builder = await _member(db, ctx, OrgRoleName.BUILDER)
    viewer = await _member(db, ctx, OrgRoleName.VIEWER)
    assert (await service.read(builder, agent.id, waiting.id)).can_restart
    assert not (await service.read(viewer, agent.id, waiting.id)).can_restart
    with pytest.raises(NotFoundError):
        await service.estimate_continuation(
            viewer, agent.id, waiting.id, ImprovementContinue(budget_usd=waiting.budget_usd)
        )

    moved = await service.continue_run(
        builder, agent.id, waiting.id, await _consent(service, builder, agent, waiting)
    )
    row = await db.get(ImprovementRun, waiting.id)
    assert row is not None
    assert (row.actor_user_id, row.actor_api_key_id) == (builder.user_id, None)
    assert any(
        event.action == "improvement.next_step_taken" and event.actor_user_id == builder.user_id
        for event in moved.timeline
    )
    seen: list[tuple[object, object]] = []
    from app.services import improvement_pipeline

    real = improvement_pipeline.job_context

    async def acting(db, *, organization_id, user_id, api_key_id):
        seen.append((user_id, api_key_id))
        return await real(
            db, organization_id=organization_id, user_id=user_id, api_key_id=api_key_id
        )

    with patch.object(improvement_pipeline, "job_context", acting):
        await service.advance(waiting.id, ctx.organization_id)
    assert seen == [(builder.user_id, None)]


async def test_a_note_goes_only_with_try_again(db):
    ctx, agent, waiting = await _at_understand(db)
    service = ImprovementPipelineService(db)
    consent = (await _consent(service, ctx, agent, waiting)).model_copy(
        update={"note": "Mind the refund window"}
    )
    with pytest.raises(BadRequestError) as refused:
        await service.continue_run(ctx, agent.id, waiting.id, consent)
    assert refused.value.details == {
        "fields": [{"field": "note", "message": "A note goes only with Try again"}]
    }
    assert (await service.read(ctx, agent.id, waiting.id)).status == "waiting"


@pytest.mark.security
async def test_a_session_stopped_for_permission_resumes_for_free_as_whoever_continues_it(db):
    ctx, agent, waiting = await _at_understand(db)
    row = await db.get(ImprovementRun, waiting.id)
    assert row is not None
    row.status, row.stage, row.stop_reason = "stopped", "judging", "permission"
    await db.flush()
    service = ImprovementPipelineService(db)
    quote = await service.estimate_continuation(
        ctx, agent.id, waiting.id, ImprovementContinue(budget_usd=waiting.budget_usd)
    )
    assert (quote.mode, quote.total_usd) == ("resume", Decimal(0))
    resumed = await _next_step(db, ctx, waiting.id)
    assert (resumed.status, resumed.stage) == ("running", "judging")


async def test_a_waiting_session_is_cancelled_and_its_stops_are_told_to_its_person(db):
    ctx, agent, waiting = await _at_changes(db)
    summaries = [
        notice.summary
        for notice in await db.scalars(
            select(Notification).where(Notification.event_type == "improvement_finished")
        )
    ]
    assert any("has read its examples" in summary for summary in summaries)
    assert any("has changes to choose from" in summary for summary in summaries)
    cancelled = await ImprovementPipelineService(db).cancel(ctx, agent.id, waiting.id)
    assert cancelled.status == "cancelled"


async def test_an_edit_at_changes_is_what_the_check_measures_and_what_accept_writes(db):
    from app.agents.spec import AgentSpec
    from app.db.models.agent import Agent
    from app.schemas.improvement import ChangeEdit
    from app.services.authoring import AuthoringService

    ctx, agent, waiting = await _at_changes(db)
    service = ImprovementPipelineService(db)
    changes = await service.changes(ctx, agent.id, waiting.id)
    hunks = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=waiting.iterations[0].batch_id
    )
    assert {change.id for change in changes} == {hunk.id for hunk in hunks}
    hunk = next(hunk for hunk in hunks if hunk.kind == "instructions")
    reworded = f"{hunk.new_text} REWORDED_BY_A_PERSON"

    edited = await service.edit_change(
        ctx, agent.id, waiting.id, hunk.id, ChangeEdit(edited_text=reworded)
    )
    assert edited.edited_text == reworded
    row = await db.get(ImprovementRun, waiting.id)
    stored_agent = await db.get(Agent, agent.id)
    assert row is not None and stored_agent is not None
    [attempt] = await improvement_repo.list_iterations(
        db, organization_id=ctx.organization_id, run_id=row.id
    )
    measured, _ = await service._candidate(stored_agent, row, attempt)
    assert "REWORDED_BY_A_PERSON" in measured.instructions
    assert attempt.candidate_spec_hash != waiting.iterations[0].candidate_spec_hash
    accepted, written = AuthoringService(db)._accepted(
        AgentSpec.model_validate(stored_agent.draft_spec), hunk, None
    )
    assert "REWORDED_BY_A_PERSON" in accepted.instructions
    assert written == {"accepted_text": reworded}

    restored = await service.edit_change(
        ctx, agent.id, waiting.id, hunk.id, ChangeEdit(edited_text=None)
    )
    assert restored.edited_text is None
    assert attempt.candidate_spec_hash == waiting.iterations[0].candidate_spec_hash


@pytest.mark.security
async def test_a_change_is_edited_only_at_the_stop_by_whoever_may_continue_and_only_its_text(db):
    from app.schemas.improvement import ChangeEdit

    ctx, agent, waiting = await _at_changes(db)
    service = ImprovementPipelineService(db)
    hunks = await authoring_repo.list_hunks(
        db, organization_id=ctx.organization_id, batch_id=waiting.iterations[0].batch_id
    )
    hunk = next(hunk for hunk in hunks if hunk.kind == "instructions")
    reword = ChangeEdit(edited_text="Reworded")
    with pytest.raises(NotFoundError, match="Change not found"):
        await service.edit_change(ctx, agent.id, waiting.id, uuid4(), reword)
    viewer = await _member(db, ctx, OrgRoleName.VIEWER)
    with pytest.raises(NotFoundError):
        await service.edit_change(viewer, agent.id, waiting.id, hunk.id, reword)
    field = SimpleNamespace(
        id=hunk.id, batch_id=hunk.batch_id, status=hunk.status, kind="spec_field"
    )
    with (
        patch(
            "app.services.improvement_pipeline.authoring_repo.get_hunk",
            AsyncMock(return_value=field),
        ),
        pytest.raises(BadRequestError) as refused,
    ):
        await service.edit_change(ctx, agent.id, waiting.id, hunk.id, reword)
    assert refused.value.details == {
        "fields": [
            {
                "field": "edited_text",
                "message": "Only a change to the instructions has text to edit",
            }
        ]
    }
    await service.continue_run(
        ctx, agent.id, waiting.id, await _consent(service, ctx, agent, waiting)
    )
    with pytest.raises(BadRequestError, match="edited only while"):
        await service.edit_change(ctx, agent.id, waiting.id, hunk.id, reword)


def _a_week_ago():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) - timedelta(days=7, minutes=1)


async def test_a_session_left_waiting_for_a_week_expires_and_its_person_is_told(db):
    ctx, agent, waiting = await _at_understand(db)
    row = await db.get(ImprovementRun, waiting.id)
    assert row is not None
    row.stage_started_at = _a_week_ago()
    await db.flush()
    await ImprovementPipelineService(db).sweep()
    assert (row.status, row.stop_reason) == ("stale", "expired")
    summaries = [
        notice.summary
        for notice in await db.scalars(
            select(Notification).where(Notification.event_type == "improvement_finished")
        )
    ]
    assert any("nobody took the next step for seven days" in summary for summary in summaries)


@pytest.mark.parametrize("change", ["draft", "archived", "dataset_gone"])
async def test_a_waiting_session_goes_stale_at_once_when_what_it_measures_changes(db, change):
    from app.db.models.agent import Agent

    ctx, agent, waiting = await _at_understand(db)
    row = await db.get(ImprovementRun, waiting.id)
    stored = await db.get(Agent, agent.id)
    assert row is not None and stored is not None
    if change == "draft":
        stored.draft_spec = {**stored.draft_spec, "instructions": "Changed under the session."}
    elif change == "archived":
        stored.status = "archived"
    else:
        row.dataset_id = uuid4()
    await db.flush()
    await ImprovementPipelineService(db).sweep()
    assert (row.status, row.stop_reason) == ("stale", "stale")


@pytest.mark.security
@pytest.mark.parametrize("who", ["left", "key_gone", "no_runs_view", "hidden"])
async def test_a_session_whose_person_lost_access_is_left_for_them_to_be_told(db, who):
    from app.core.permissions import Perm
    from app.db.models.agent import Agent
    from app.schemas.api_key import ApiKeyCreate
    from app.services.api_key import ApiKeyService

    ctx, agent, waiting = await _at_understand(db)
    row = await db.get(ImprovementRun, waiting.id)
    stored = await db.get(Agent, agent.id)
    assert row is not None and stored is not None
    stored.draft_spec = {**stored.draft_spec, "instructions": "Changed under the session."}
    if who == "left":
        row.created_by_user_id = None
    elif who == "key_gone":
        row.actor_user_id, row.actor_api_key_id = ctx.user_id, uuid4()
    elif who == "no_runs_view":
        key = await ApiKeyService(db).create(
            ctx,
            ApiKeyCreate(name="no runs", scopes=[Perm.AGENTS_VIEW, Perm.AGENTS_EDIT]),
        )
        row.actor_user_id, row.actor_api_key_id = ctx.user_id, key.id
    else:
        viewer = await _member(db, ctx, OrgRoleName.VIEWER)
        row.actor_user_id = viewer.user_id
    await db.flush()
    await ImprovementPipelineService(db).sweep()
    assert row.status == "waiting"


async def test_a_ready_session_outlives_its_draft_moving_but_not_a_week(db):
    from app.db.models.agent import Agent
    from tests.integration.test_improvement_pipeline import _ready_proposal

    ctx, agent, ready = await _ready_proposal(db)
    row = await db.get(ImprovementRun, ready.id)
    stored = await db.get(Agent, agent.id)
    assert row is not None and stored is not None
    stored.draft_spec = {**stored.draft_spec, "instructions": "Changed in the Builder."}
    await db.flush()
    service = ImprovementPipelineService(db)
    await service.sweep()
    assert row.status == "ready"
    row.stage_started_at = _a_week_ago()
    await db.flush()
    await service.sweep()
    assert (row.status, row.stop_reason) == ("stale", "expired")


async def test_a_failed_session_can_be_stopped(db):
    ctx, agent, waiting = await _at_understand(db)
    row = await db.get(ImprovementRun, waiting.id)
    assert row is not None
    row.status, row.stage, row.stop_reason = "failed", "proposing", "proposal"
    await db.flush()
    stopped = await ImprovementPipelineService(db).cancel(ctx, agent.id, waiting.id)
    assert stopped.status == "cancelled"
