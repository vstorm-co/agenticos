"""Browser teaching refusals and reconciliation paths against a real database.

The capture and review modules prove the happy path and the main refusals. These
tests cover what is left: a wrong state, a stale revision, a lost race on start,
a resume that cannot be honoured, a limit hit on write, a job that finds nothing
to do, and the sweep's own decisions about a recording.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.browser_teaching import (
    Observation,
    TeachingConflict,
    TeachingReason,
    TeachingRefused,
    TeachingState,
)
from app.core.config import settings
from app.db.models.browser_teaching import BrowserTeachingSession
from app.db.models.organization import OrganizationMember
from app.db.models.skill_proposal import SkillProposal
from app.repositories import browser_teaching as repo
from app.schemas.browser_teaching import TeachingChange, TeachingPropose, TeachingStart
from app.services.browser_teaching import _hold, _service, _sweep
from app.services.browser_teaching._hold import Hold
from app.services.browser_teaching._service import BrowserTeachingService, pause
from tests.integration import test_browser_teaching_capture as capture
from tests.integration import test_browser_teaching_review as review
from tests.integration.test_browser_teaching_capture import (
    ORIGIN,
    _contexts,
    _ctx,
    _hold_for,
    _noop,
    _recording,
    _seen,
    _start,
)

pytestmark = pytest.mark.anyio

# Fixtures bound by assignment so pytest finds them here (an import shadowed by a
# parameter is a redefinition to ruff).
enabled = capture.enabled
redis = capture.redis

RESUME = TeachingChange(action="resume")
PAUSE = TeachingChange(action="pause")


async def _set(db: Any, session_id: uuid.UUID, **values: Any) -> None:
    await db.execute(
        update(BrowserTeachingSession)
        .where(BrowserTeachingSession.id == session_id)
        .values(**values)
    )
    await db.flush()


def _sweeping(monkeypatch: pytest.MonkeyPatch, db: Any, redis: Any) -> None:
    monkeypatch.setattr(_sweep.live_browse, "client", lambda: redis)
    monkeypatch.setattr(_sweep.live_browse, "connect_in_worker", _noop)
    monkeypatch.setattr(_sweep, "get_db_context", _contexts(db))


async def test_pausing_a_row_that_is_not_recording_changes_nothing(db, redis, enabled) -> None:
    _, _, _, _, _, _, started = await _recording(db, redis, enabled)
    row = await db.get(BrowserTeachingSession, started.id)
    row.status = TeachingState.REVIEW.value
    pause(row, TeachingReason.PAUSED_BY_OWNER)
    assert (row.status, row.reason_code, row.revision) == ("review", None, started.revision)


async def test_a_session_past_its_retention_is_erased_when_its_owner_reads_it(
    db, redis, enabled
) -> None:
    organization, owner, _, _, _, service, started = await _recording(db, redis, enabled)
    await _set(db, started.id, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    read = await service.get(_ctx(owner, organization), started.id)
    assert (read.status, read.reason_code, read.events) == (
        TeachingState.EXPIRED,
        TeachingReason.EXPIRED,
        (),
    )


async def test_a_hold_of_another_agent_cannot_start_a_session_on_the_run(
    db, redis, enabled
) -> None:
    organization, owner, _, run, _, service, _ = await _recording(db, redis, enabled)
    foreign = Hold(
        organization_id=run.organization_id,
        run_id=run.id,
        agent_id=uuid.uuid4(),
        user_id=owner.id,
        call_id="call-2",
        tab_id="main",
        hold_id=uuid.uuid4(),
    )
    assert await _hold.claim(redis, foreign)
    with pytest.raises(TeachingRefused) as refused:
        await service.start(_ctx(owner, organization), _start(run, "call-2"), "key-2")
    assert refused.value.reason == TeachingReason.NOT_HELD


async def _raced_start(db, redis, enabled, monkeypatch, *, same_body: bool):
    """A retry whose first lookup misses while the original insert is still uncommitted."""
    organization, owner, _, run, _, service, started = await _recording(db, redis, enabled)
    row = await db.get(BrowserTeachingSession, started.id)
    answers = iter([None, row])

    async def by_request(*_args: Any) -> BrowserTeachingSession | None:
        return next(answers)

    monkeypatch.setattr(repo, "by_request", by_request)
    body = (
        _start(run)
        if same_body
        else TeachingStart(
            run_id=run.id, call_id="call-1", title="Other", allowed_origins=(ORIGIN,)
        )
    )
    return started, service.start(_ctx(owner, organization), body, "key-1")


async def test_a_retry_that_loses_the_first_lookup_still_returns_the_original(
    db, redis, enabled, monkeypatch
) -> None:
    started, outcome = await _raced_start(db, redis, enabled, monkeypatch, same_body=True)
    assert (await outcome).id == started.id


async def test_a_retry_with_another_body_that_loses_the_first_lookup_conflicts(
    db, redis, enabled, monkeypatch
) -> None:
    _, outcome = await _raced_start(db, redis, enabled, monkeypatch, same_body=False)
    with pytest.raises(TeachingConflict) as conflict:
        await outcome
    assert conflict.value.reason == TeachingReason.REQUEST_REUSED


@pytest.mark.parametrize("same_request", [True, False])
async def test_a_concurrent_insert_is_resolved_to_the_winner_or_a_conflict(
    db, redis, enabled, monkeypatch, same_request
) -> None:
    organization, owner, agent, run, _, _, started = await _recording(db, redis, enabled)
    await _hold_for(redis, run, owner, call_id="call-2")
    winner = await db.get(BrowserTeachingSession, started.id)
    service = BrowserTeachingService(db, redis)
    body = TeachingStart(run_id=run.id, call_id="call-2", title="Second", allowed_origins=(ORIGIN,))
    lookups = iter([None, None, winner if same_request else None])

    async def by_request(*_args: Any) -> BrowserTeachingSession | None:
        return next(lookups)

    async def lost_race(_db: Any, _row: Any) -> BrowserTeachingSession:
        raise IntegrityError("insert", {}, Exception("duplicate"))

    monkeypatch.setattr(repo, "by_request", by_request)
    monkeypatch.setattr(repo, "create", lost_race)
    if same_request:
        winner.request_fingerprint = _service._digest(body.model_dump_json())
        assert (await service.start(_ctx(owner, organization), body, "key-2")).id == winner.id
        return
    with pytest.raises(TeachingConflict) as conflict:
        await service.start(_ctx(owner, organization), body, "key-2")
    assert conflict.value.reason == TeachingReason.ALREADY_RECORDING


async def test_review_and_proposal_need_a_session_in_review(db, redis, enabled) -> None:
    organization, owner, _, _, _, service, started = await _recording(db, redis, enabled)
    ctx = _ctx(owner, organization)
    with pytest.raises(TeachingConflict) as conflict:
        await service.review(ctx, started.id, review._review(), started.revision)
    assert conflict.value.reason == TeachingReason.WRONG_STATE
    with pytest.raises(TeachingConflict) as conflict:
        await service.propose(
            ctx, started.id, TeachingPropose(name="download-invoice"), started.revision
        )
    assert conflict.value.reason == TeachingReason.WRONG_STATE


async def test_a_proposal_from_a_stale_revision_conflicts(db, redis, enabled) -> None:
    organization, owner, service, reviewed = await review._reviewed(db, redis, enabled)
    with pytest.raises(TeachingConflict) as conflict:
        await service.propose(
            _ctx(owner, organization),
            reviewed.id,
            TeachingPropose(name="download-invoice"),
            reviewed.revision - 1,
        )
    assert conflict.value.reason == TeachingReason.STALE_REVISION


async def test_a_proposal_cannot_take_a_name_a_skill_already_has(
    db, redis, enabled, monkeypatch
) -> None:
    organization, owner, service, reviewed = await review._reviewed(db, redis, enabled)

    async def taken(*_args: Any, **_kwargs: Any) -> object:
        return object()

    monkeypatch.setattr(_service.skill_repo, "get_by_name", taken)
    with pytest.raises(TeachingRefused) as refused:
        await service.propose(
            _ctx(owner, organization),
            reviewed.id,
            TeachingPropose(name="download-invoice"),
            reviewed.revision,
        )
    assert refused.value.reason == TeachingReason.SKILL_NAME
    assert await review._jobs(db) == 0


async def test_a_queued_build_for_an_expired_session_erases_it_and_writes_no_proposal(
    db, redis, enabled
) -> None:
    organization, owner, service, reviewed = await review._reviewed(db, redis, enabled)
    queued = await service.propose(
        _ctx(owner, organization),
        reviewed.id,
        TeachingPropose(name="download-invoice"),
        reviewed.revision,
    )
    row = await db.get(BrowserTeachingSession, queued.id)
    await _set(db, queued.id, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    await db.refresh(row)
    await service.build_proposal(organization.id, queued.id, row.source_hash)
    await db.refresh(row)
    assert (row.status, row.sanitized_events) == ("expired", [])
    assert await review._proposals(db, queued.id) == []


async def test_a_build_that_finds_its_proposal_already_written_only_closes_the_session(
    db, redis, enabled
) -> None:
    organization, owner, service, reviewed = await review._reviewed(db, redis, enabled)
    ctx = _ctx(owner, organization)
    queued = await service.propose(
        ctx, reviewed.id, TeachingPropose(name="download-invoice"), reviewed.revision
    )
    row = await db.get(BrowserTeachingSession, queued.id)
    await service.build_proposal(organization.id, queued.id, row.source_hash)
    await _set(db, queued.id, status="proposing")
    await db.refresh(row)
    await service.build_proposal(organization.id, queued.id, row.source_hash)
    await db.refresh(row)
    assert row.status == "proposed"
    count = await db.scalar(
        select(func.count())
        .select_from(SkillProposal)
        .where(SkillProposal.browser_teaching_id == queued.id)
    )
    assert count == 1


async def test_pausing_needs_a_recording_session(db, redis, enabled) -> None:
    organization, owner, _, _, _, service, started = await _recording(db, redis, enabled)
    ctx = _ctx(owner, organization)
    paused = await service.change(ctx, started.id, PAUSE, started.revision)
    with pytest.raises(TeachingConflict) as conflict:
        await service.change(ctx, started.id, PAUSE, paused.revision)
    assert conflict.value.reason == TeachingReason.WRONG_STATE


async def test_resuming_needs_a_paused_session(db, redis, enabled) -> None:
    organization, owner, _, _, _, service, started = await _recording(db, redis, enabled)
    with pytest.raises(TeachingConflict) as conflict:
        await service.change(_ctx(owner, organization), started.id, RESUME, started.revision)
    assert conflict.value.reason == TeachingReason.WRONG_STATE


async def test_a_session_past_its_capture_time_cannot_resume(db, redis, enabled) -> None:
    organization, owner, _, _, _, service, started = await _recording(db, redis, enabled)
    ctx = _ctx(owner, organization)
    paused = await service.change(ctx, started.id, PAUSE, started.revision)
    await _set(db, started.id, capture_ends_at=datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(TeachingRefused) as refused:
        await service.change(ctx, started.id, RESUME, paused.revision)
    assert refused.value.reason == TeachingReason.TIME_LIMIT


async def test_a_session_cannot_resume_on_another_tab_of_the_run(db, redis, enabled) -> None:
    organization, owner, _, run, hold, service, started = await _recording(db, redis, enabled)
    ctx = _ctx(owner, organization)
    paused = await service.change(ctx, started.id, PAUSE, started.revision)
    await _hold.release(redis, hold)
    await _hold_for(redis, run, owner, tab="second")
    with pytest.raises(TeachingRefused) as refused:
        await service.change(ctx, started.id, RESUME, paused.revision)
    assert refused.value.reason == TeachingReason.NOT_HELD


async def test_stopping_a_closed_session_is_a_conflict_and_discarding_one_changes_nothing(
    db, redis, enabled
) -> None:
    organization, owner, _, _, _, service, started = await _recording(db, redis, enabled)
    ctx = _ctx(owner, organization)
    await service.discard(ctx, started.id)
    with pytest.raises(TeachingConflict) as conflict:
        await service.stop(ctx, started.id)
    assert conflict.value.reason == TeachingReason.WRONG_STATE
    row = await db.get(BrowserTeachingSession, started.id)
    revision = row.revision
    await service.discard(ctx, started.id)
    await db.refresh(row)
    assert (row.status, row.revision) == ("discarded", revision)


async def test_a_hold_that_is_not_the_recordings_does_not_pause_it(db, redis, enabled) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    other = hold.model_copy(update={"hold_id": uuid.uuid4()})
    await service.release(other, TeachingReason.OWNERSHIP_LOST)
    assert (
        await service.get(_ctx(owner, organization), started.id)
    ).status == TeachingState.RECORDING
    await service.release(hold, TeachingReason.OWNERSHIP_LOST)
    assert (await service.get(_ctx(owner, organization), started.id)).status == TeachingState.PAUSED


async def test_a_step_that_would_overflow_the_byte_budget_pauses_capture(
    db, redis, enabled, monkeypatch
) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    monkeypatch.setattr(_service, "MAX_EVENT_BYTES", 10)
    await service.record(hold, input_id=uuid.uuid4(), action="click", observation=_seen())
    read = await service.get(_ctx(owner, organization), started.id)
    assert (read.status, read.reason_code, read.events) == (
        TeachingState.PAUSED,
        TeachingReason.BYTE_LIMIT,
        (),
    )


async def test_the_flag_turned_off_mid_recording_pauses_on_the_next_step(
    db, redis, enabled, monkeypatch
) -> None:
    organization, owner, _, _, hold, service, started = await _recording(db, redis, enabled)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    await service.record(
        hold, input_id=uuid.uuid4(), action="navigate", observation=Observation(origin=ORIGIN)
    )
    read = await service.get(_ctx(owner, organization), started.id)
    assert (read.status, read.reason_code) == (TeachingState.PAUSED, TeachingReason.DISABLED)


async def test_the_sweep_pauses_a_recording_that_ran_out_of_capture_time(
    db, redis, enabled, monkeypatch
) -> None:
    _, _, _, _, _, _, started = await _recording(db, redis, enabled)
    await _set(db, started.id, capture_ends_at=datetime.now(UTC) - timedelta(seconds=1))
    _sweeping(monkeypatch, db, redis)
    await _sweep.sweep_browser_teachings()
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.reason_code) == ("paused", "capture_time_limit_reached")


async def test_the_sweep_pauses_a_recording_when_the_flag_is_off(
    db, redis, enabled, monkeypatch
) -> None:
    _, _, _, _, _, _, started = await _recording(db, redis, enabled)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    _sweeping(monkeypatch, db, redis)
    await _sweep.sweep_browser_teachings()
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.reason_code) == ("paused", "teaching_disabled")


async def test_the_sweep_pauses_a_recording_whose_owner_lost_authority(
    db, redis, enabled, monkeypatch
) -> None:
    _, owner, _, _, _, _, started = await _recording(db, redis, enabled)
    await db.execute(
        update(OrganizationMember)
        .where(OrganizationMember.user_id == owner.id)
        .values(role="viewer")
    )
    _sweeping(monkeypatch, db, redis)
    await _sweep.sweep_browser_teachings()
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.reason_code) == ("paused", "authority_changed")


async def test_the_sweep_leaves_a_healthy_recording_and_a_paused_session_alone(
    db, redis, enabled, monkeypatch
) -> None:
    organization, owner, _, _, _, service, started = await _recording(db, redis, enabled)
    _sweeping(monkeypatch, db, redis)
    await _sweep.sweep_browser_teachings()
    row = await db.get(BrowserTeachingSession, started.id)
    assert (row.status, row.revision) == ("recording", started.revision)
    await service.change(_ctx(owner, organization), started.id, PAUSE, started.revision)
    await _sweep.sweep_browser_teachings()
    await db.refresh(row)
    assert row.status == "paused"


async def test_the_sweep_skips_a_candidate_that_vanished(db, redis, enabled, monkeypatch) -> None:
    _, _, _, _, _, _, started = await _recording(db, redis, enabled)
    _sweeping(monkeypatch, db, redis)
    real = repo.get

    async def gone(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(repo, "get", gone)
    assert await _sweep.sweep_browser_teachings() == 0
    monkeypatch.setattr(repo, "get", real)
    assert (await db.get(BrowserTeachingSession, started.id)).status == "recording"
