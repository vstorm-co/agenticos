"""Waiting, resumed and completed work cannot replace its original live authority."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingObservation,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingReviewedAction,
)
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.agent_run import RunStatus
from app.repositories import browser_procedure_teaching as repo
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingChange
from app.services.browser_procedure_teaching import _refinement, _service
from tests.integration.test_browser_procedure_teaching import draft_runtime as draft_runtime
from tests.integration.test_browser_procedure_teaching import teaching as teaching
from tests.integration.test_browser_procedure_teaching_generation_edges import queued
from tests.integration.test_browser_procedure_teaching_refinement import identity, opt_in, start
from tests.test_browser_procedure_teaching_contracts import ORIGIN, TARGET, review

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("changed", [False, True])
async def test_concurrent_start_rechecks_the_complete_request_after_the_policy_lock(
    teaching, monkeypatch, changed
):
    t = teaching
    request = t.request()
    original = await t.service.start(t.ctx, request)
    row = await repo.session(t.db, t.org.id, original.id)
    if changed:
        row.request_fingerprint = "0" * 64
        await t.db.flush()
    fetch = repo.session
    calls = 0

    async def read_after_lock(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else await fetch(*args, **kwargs)

    monkeypatch.setattr(repo, "session", read_after_lock)
    if changed:
        with pytest.raises(NotFoundError):
            await t.service.start(t.ctx, request)
    else:
        assert await t.service.start(t.ctx, request) == original
    assert calls == 2


async def test_twenty_outstanding_owner_sessions_block_new_capture_until_one_is_discarded(teaching):
    t = teaching
    first = None
    for _ in range(20):
        data = await t.start()
        first = first or data
        await t.service.stop(t.ctx, data.id)
    assert await repo.owner_open_count(t.db, t.org.id, t.owner.id) == 20
    with pytest.raises(ConflictError):
        await t.start()
    await t.service.discard(t.ctx, first.id)
    assert (await t.start()).status == "recording"


@pytest.mark.parametrize("change", ["missing", "takeover_id", "tab_id"])
async def test_start_requires_the_current_server_minted_takeover(teaching, monkeypatch, change):
    t = teaching
    held = (
        None
        if change == "missing"
        else t.held.model_copy(
            update={
                change: "other-tab" if change == "tab_id" else uuid4(),
            }
        )
    )
    monkeypatch.setattr(_service, "discover", AsyncMock(return_value=held))
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.start()
    assert caught.value.reason == BrowserProcedureTeachingReason.OWNERSHIP_LOST


@pytest.mark.parametrize(
    "case",
    ["pause_review", "resume_recording", "resume_expired", "review_recording", "review_queued"],
)
async def test_invalid_review_or_resume_transitions_cannot_change_the_capture(
    teaching, draft_runtime, case
):
    t = teaching
    if case == "review_queued":
        data, row, _ = await queued(t, draft_runtime)
        data = await t.service.get(t.ctx, data.id)
        action = BrowserProcedureTeachingChange(action="review", review=data.review)
    else:
        data = await t.start()
        action = BrowserProcedureTeachingChange(
            action="review",
            review=review(
                BrowserProcedureTeachingReviewedAction(
                    sequence=1, label="Reviewed structural action"
                )
            ),
        )
        if case == "pause_review":
            data = await t.service.stop(t.ctx, data.id)
            action = BrowserProcedureTeachingChange(action="pause")
        elif case in {"resume_recording", "resume_expired"}:
            if case == "resume_expired":
                data = await t.service.change(
                    t.ctx, data.id, data.revision, BrowserProcedureTeachingChange(action="pause")
                )
                row = await repo.session(t.db, t.org.id, data.id)
                row.capture_ends_at = datetime.now(UTC) - timedelta(seconds=1)
                await t.db.flush()
            action = BrowserProcedureTeachingChange(action="resume", takeover_id=t.held.takeover_id)
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.service.change(t.ctx, data.id, data.revision, action)
    assert caught.value.reason == (
        BrowserProcedureTeachingReason.TIME_LIMIT
        if case.startswith("resume")
        else BrowserProcedureTeachingReason.REVIEW_REQUIRED
    )


@pytest.mark.parametrize(
    "field", ["missing", "controller_id", "tab_id", "user_id", "organization_id", "agent_id"]
)
async def test_resume_rechecks_the_live_controller_and_exact_owner_identity(
    teaching, monkeypatch, field
):
    t = teaching
    data = await t.start()
    data = await t.service.change(
        t.ctx, data.id, data.revision, BrowserProcedureTeachingChange(action="pause")
    )
    observed = (
        None
        if field == "missing"
        else t.held.model_copy(
            update={
                field: "other" if field == "tab_id" else uuid4(),
            }
        )
    )
    monkeypatch.setattr(_service, "discover", AsyncMock(return_value=observed))
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.service.change(
            t.ctx,
            data.id,
            data.revision,
            BrowserProcedureTeachingChange(action="resume", takeover_id=t.held.takeover_id),
        )
    assert caught.value.reason == BrowserProcedureTeachingReason.OWNERSHIP_LOST
    assert (await t.service.get(t.ctx, data.id)).status == "paused"


async def test_pause_live_and_repeated_stop_never_affect_another_capture(teaching):
    t = teaching
    assert await t.service.pause_live(t.held, BrowserProcedureTeachingReason.OWNERSHIP_LOST) is None
    data = await t.start()
    other = t.held.model_copy(update={"call_id": "other"})
    assert await t.service.pause_live(other, BrowserProcedureTeachingReason.OWNERSHIP_LOST) is None
    paused = await t.service.pause_live(t.held, BrowserProcedureTeachingReason.OWNERSHIP_LOST)
    assert paused.status == "paused"
    stopped = await t.service.stop(t.ctx, data.id)
    assert stopped.status == "review"
    assert await t.service.stop(t.ctx, data.id) == stopped


@pytest.mark.parametrize("change", ["preference", "missing_preference", "draft_run", "learning"])
async def test_refinement_opt_in_is_rechecked_after_waiting_for_policy_lock(
    teaching, monkeypatch, change
):
    t = teaching
    preference = await opt_in(t)
    fetch = repo.policy

    async def locked_policy(*args, **kwargs):
        result = await fetch(*args, **kwargs)
        if kwargs.get("locked"):
            if change == "preference":
                preference.enabled = False
            elif change == "missing_preference":
                await t.db.delete(preference)
            elif change == "draft_run":
                t.run.test_spec = t.version.spec
            else:
                binding = t.version.spec["capabilities"][0]
                t.version.spec = {
                    **t.version.spec,
                    "capabilities": [
                        {**binding, "config": {**binding["config"], "learn_site_procedures": False}}
                    ],
                }
            await t.db.flush()
        return result

    monkeypatch.setattr(repo, "policy", locked_policy)
    assert await _refinement.start(t.db, t.ctx, identity(t), ORIGIN) is None
    assert await repo.owner_open_count(t.db, t.org.id, t.owner.id) == 0


@pytest.mark.parametrize("condition", ["expired", "completed", "failed", "revoked"])
async def test_refinement_final_effect_requires_time_and_current_success_evidence(
    teaching, condition
):
    t = teaching
    data = await start(t)
    row = await repo.session(t.db, t.org.id, data.id)
    expected = BrowserProcedureTeachingReason.TASK_NOT_COMPLETED
    if condition == "expired":
        row.capture_ends_at = datetime.now(UTC) - timedelta(seconds=1)
        expected = BrowserProcedureTeachingReason.TIME_LIMIT
    elif condition == "revoked":
        (await repo.policy(t.db, t.org.id)).generation = uuid4()
        expected = BrowserProcedureTeachingReason.AUTHORITY_CHANGED
    else:
        t.run.status = (
            RunStatus.COMPLETED.value if condition == "completed" else RunStatus.FAILED.value
        )
    await t.db.flush()
    finished = await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True)
    if condition == "completed":
        assert (
            finished.status == "review"
            and finished.verified_success
            and finished.reason_code is None
        )
    else:
        assert finished.status == "discarded" and not finished.events
        assert finished.reason_code == expected and not finished.verified_success
    assert await _refinement.finish(t.db, t.ctx, identity(t), data.id, completed=True) == finished


@pytest.mark.parametrize("condition", ["missing", "other", "stopped", "expired"])
async def test_refinement_append_does_not_resume_a_missing_other_or_terminal_capture(
    teaching, condition
):
    t = teaching
    data = await start(t)
    session_id, held = data.id, identity(t)
    if condition == "missing":
        session_id = uuid4()
    elif condition == "other":
        held = held.model_copy(update={"controller_id": uuid4()})
    elif condition == "stopped":
        await _refinement.finish(t.db, t.ctx, held, data.id, completed=False)
    else:
        row = await repo.session(t.db, t.org.id, data.id)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await t.db.flush()
    args = {
        "input_id": uuid4(),
        "action": "click",
        "observation": BrowserProcedureTeachingObservation(origin=ORIGIN, target=TARGET),
    }
    if condition in {"missing", "other"}:
        with pytest.raises(BrowserProcedureTeachingRefused) as caught:
            await _refinement.append(t.db, t.ctx, held, session_id, **args)
        assert caught.value.reason == BrowserProcedureTeachingReason.OWNERSHIP_LOST
    else:
        saved = await _refinement.append(t.db, t.ctx, held, session_id, **args)
        assert saved.status == ("discarded" if condition == "stopped" else "expired")
        assert not saved.events
