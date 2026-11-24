"""Opt-in recordings need native-task and final-run completion before reviewed drafts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingObservation,
    BrowserProcedureTeachingParameter,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingReviewedAction,
)
from app.db.models.agent_run import RunStatus
from app.db.models.browser_procedure_teaching import BrowserProcedureTeachingPreference
from app.repositories import browser_procedure_teaching as repo
from app.schemas.browser_procedure_teaching import (
    BrowserProcedureTeachingChange,
    BrowserProcedureTeachingPreferenceWrite,
)
from app.services.browser_procedure_teaching import _access, _refinement
from app.services.browser_procedure_teaching._lease import BrowserProcedureTeachingIdentity
from app.services.browser_procedure_teaching._policy import BrowserProcedureTeachingPolicyService
from tests.integration.test_browser_procedure_teaching import teaching as teaching
from tests.test_browser_procedure_teaching_contracts import ORIGIN, SECRET, TARGET, review

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def identity(t):
    return BrowserProcedureTeachingIdentity.model_validate(
        t.held.model_dump(exclude={"connection_id", "takeover_id"})
    )


async def opt_in(t):
    row = BrowserProcedureTeachingPreference(
        organization_id=t.org.id,
        user_id=t.owner.id,
        agent_id=t.agent.id,
        enabled=True,
        generation=uuid4(),
    )
    t.db.add(row)
    await t.db.flush()
    return row


async def start(t):
    await opt_in(t)
    data = await _refinement.start(t.db, t.ctx, identity(t), ORIGIN)
    assert data is not None
    return data


def chosen_review():
    return review(
        BrowserProcedureTeachingReviewedAction(
            sequence=1, label="Open the approved site", path_template="/items"
        ),
        BrowserProcedureTeachingReviewedAction(
            sequence=2, label="Search for the requested record", parameter="record"
        ),
        parameters=(
            BrowserProcedureTeachingParameter(name="record", description="The requested record"),
        ),
    )


async def test_learning_is_off_without_the_exact_member_choice(teaching):
    t = teaching
    assert await _refinement.start(t.db, t.ctx, identity(t), ORIGIN) is None
    pref = await opt_in(t)
    pref.enabled = False
    await t.db.flush()
    assert await _refinement.start(t.db, t.ctx, identity(t), ORIGIN) is None
    pref.enabled = True
    t.run.test_spec = t.version.spec
    await t.db.flush()
    assert await _refinement.start(t.db, t.ctx, identity(t), ORIGIN) is None


async def test_browser_done_is_not_final_run_success_and_review_cannot_promote_it(teaching):
    t = teaching
    data = await start(t)
    row = await repo.session(t.db, t.org.id, data.id)
    assert row.connection_id is None and row.takeover_id is None
    assert data.source == "refinement" and not data.verified_success
    assert data.events[0].action == "navigate"
    assert await _refinement.start(t.db, t.ctx, identity(t), ORIGIN) is None
    await _refinement.append(
        t.db,
        t.ctx,
        identity(t),
        data.id,
        input_id=uuid4(),
        action="input_parameter",
        observation=BrowserProcedureTeachingObservation(origin=ORIGIN, target=TARGET),
    )
    stopped = await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True)
    assert stopped.status == "review" and not stopped.verified_success
    assert stopped.reason_code == BrowserProcedureTeachingReason.TASK_NOT_COMPLETED
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.service.change(
            t.ctx,
            data.id,
            stopped.revision,
            BrowserProcedureTeachingChange(action="review", review=chosen_review()),
        )
    assert caught.value.reason == BrowserProcedureTeachingReason.TASK_NOT_COMPLETED
    await _refinement.reconcile(t.db, row)
    assert not row.verified_success
    t.run.status = RunStatus.COMPLETED.value
    await t.db.flush()
    await _refinement.reconcile(t.db, row)
    await t.db.flush()
    assert row.verified_success
    reviewed = await t.service.change(
        t.ctx,
        data.id,
        row.revision,
        BrowserProcedureTeachingChange(action="review", review=chosen_review()),
    )
    assert reviewed.procedure.verified_success and reviewed.procedure.source == "refinement"
    assert SECRET not in reviewed.model_dump_json()


@pytest.mark.parametrize("status", [RunStatus.FAILED.value, RunStatus.CANCELLED.value])
async def test_failed_or_cancelled_final_run_erases_a_finished_browser_suggestion(teaching, status):
    t = teaching
    data = await start(t)
    await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True)
    row = await repo.session(t.db, t.org.id, data.id)
    t.run.status = status
    await t.db.flush()
    await _refinement.reconcile(t.db, row)
    assert row.status == "discarded" and row.sanitized_events == []
    assert (
        not row.verified_success
        and row.reason_code == BrowserProcedureTeachingReason.TASK_NOT_COMPLETED
    )


@pytest.mark.parametrize("completed", [False, True])
async def test_failed_browse_or_paused_authentication_never_becomes_success(teaching, completed):
    t = teaching
    data = await start(t)
    if completed:
        await _refinement.append(
            t.db,
            t.ctx,
            identity(t),
            data.id,
            input_id=uuid4(),
            action="click",
            observation=BrowserProcedureTeachingObservation(origin=ORIGIN, human_required=True),
        )
    result = await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=completed)
    assert result.status == "discarded" and not result.events and not result.verified_success


@pytest.mark.parametrize(
    "field",
    ["organization_id", "user_id", "agent_id", "run_id", "controller_id", "call_id", "tab_id"],
)
async def test_no_other_controller_or_run_can_extend_or_finish_a_recording(teaching, field):
    t = teaching
    data = await start(t)
    foreign = identity(t).model_copy(
        update={field: "other" if field in {"call_id", "tab_id"} else uuid4()}
    )
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _refinement.authorize_capture(t.db, t.ctx, foreign, data.id)
    assert caught.value.reason == BrowserProcedureTeachingReason.OWNERSHIP_LOST
    assert await _refinement.finish(t.db, t.ctx, foreign, data.id, completed=True) is None
    assert (await repo.session(t.db, t.org.id, data.id)).status == "recording"


async def test_rotated_member_choice_refuses_capture_even_if_enabled_again(teaching):
    t = teaching
    data = await start(t)
    pref = await repo.preference(t.db, t.org.id, t.owner.id, t.agent.id)
    pref.generation = uuid4()
    await t.db.flush()
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _refinement.authorize_capture(t.db, t.ctx, identity(t), data.id)
    assert caught.value.reason == BrowserProcedureTeachingReason.OPTED_OUT
    stopped = await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True)
    assert (
        stopped.status == "discarded"
        and stopped.reason_code == BrowserProcedureTeachingReason.OPTED_OUT
    )


async def test_member_opt_out_erases_pending_automatic_capture(teaching):
    t = teaching
    data = await start(t)
    pref = await repo.preference(t.db, t.org.id, t.owner.id, t.agent.id)
    await BrowserProcedureTeachingPolicyService(t.db).update_preference(
        t.ctx,
        t.agent.id,
        BrowserProcedureTeachingPreferenceWrite(generation=pref.generation, enabled=False),
    )
    row = await repo.session(t.db, t.org.id, data.id)
    assert row.status == "discarded" and row.sanitized_events == []


async def test_one_source_attempt_cannot_resume_through_a_new_controller(teaching):
    t = teaching
    data = await start(t)
    await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=False)
    new = identity(t).model_copy(update={"controller_id": uuid4()})
    assert await _refinement.start(t.db, t.ctx, new, ORIGIN) is None
    assert await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True)


async def test_user_stop_and_resume_cannot_forge_a_successful_automatic_task(teaching):
    t = teaching
    data = await start(t)
    paused = await t.service.change(
        t.ctx, data.id, data.revision, BrowserProcedureTeachingChange(action="pause")
    )
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.service.change(
            t.ctx,
            data.id,
            paused.revision,
            BrowserProcedureTeachingChange(action="resume", takeover_id=t.held.takeover_id),
        )
    assert caught.value.reason == BrowserProcedureTeachingReason.OWNERSHIP_LOST
    stopped = await t.service.stop(t.ctx, data.id)
    assert stopped.status == "discarded" and not stopped.verified_success


async def test_capture_deadline_and_completed_run_are_independently_checked(teaching):
    t = teaching
    data = await start(t)
    row = await repo.session(t.db, t.org.id, data.id)
    row.capture_ends_at = datetime.now(UTC) - timedelta(seconds=1)
    await t.db.flush()
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _refinement.authorize_capture(t.db, t.ctx, identity(t), data.id)
    assert caught.value.reason == BrowserProcedureTeachingReason.TIME_LIMIT
    with pytest.raises(BrowserProcedureTeachingRefused):
        _access.require_reviewable(row, t.run)
