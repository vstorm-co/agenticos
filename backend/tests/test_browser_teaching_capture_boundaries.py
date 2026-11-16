"""Ownership heartbeat, interrupted admission and the native-to-service capture seam."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.audience import RunAudience
from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.browser_use._decision import Click
from app.agents.deps import AgentDeps
from app.core.browser_teaching import TeachingReason, TeachingRefused
from app.services.browser_teaching import _capture
from tests.test_browser_teaching_capture import receipt
from tests.test_browser_teaching_capture import recorder as recorder
from tests.test_browser_teaching_contracts import ORIGIN, SECRET

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def deps(r):
    return AgentDeps(
        organization_id=r.held.organization_id,
        run_id=r.held.run_id,
        agent_id=r.held.agent_id,
        run_person=r.held.user_id,
        user_id=str(r.held.user_id),
        audience=RunAudience(user_id=r.held.user_id, browses_signed_in=True),
    )


async def test_supported_private_audience_gets_a_fresh_server_controller(recorder):
    r = recorder
    created = await _capture.BrowserTeachingCapture.create(
        deps=deps(r),
        tab_id=r.held.tab_id,
        redis=r.redis,
        page=r.page,
        guard=r.guard,
        step=lambda: 1,
    )
    assert created is not None
    assert created.identity.user_id == r.held.user_id
    assert created.identity.controller_id != r.held.controller_id
    assert created.identity.call_id == "unheld"
    raw = BrowserEvent(kind="browser_step", call_id="unheld", step=0, title="Ordinary output")
    assert created.event(raw) is raw
    await created.close()


@pytest.mark.parametrize("failure", ["refused", "cancelled"])
async def test_interrupted_takeover_admission_closes_its_prior_lease(recorder, failure):
    r = recorder
    before = r.capture._lease
    _capture._access.admit.side_effect = (
        TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
        if failure == "refused"
        else asyncio.CancelledError()
    )
    kwargs = {
        "call_id": "new-call",
        "connection_id": r.held.connection_id,
        "user_id": str(r.held.user_id),
        "emit": r.emit,
    }
    if failure == "refused":
        assert await r.capture.begin(**kwargs) is None
    else:
        with pytest.raises(asyncio.CancelledError):
            await r.capture.begin(**kwargs)
    assert r.capture._lease is None
    with pytest.raises(TeachingRefused):
        await before.check()


async def stop_heartbeat(r):
    task, r.capture._heartbeat = r.capture._heartbeat, None
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("row_kind", ["valid", "missing", "foreign", "expired", "error"])
async def test_heartbeat_checks_current_authority_and_closes_on_any_uncertain_owner(
    recorder, monkeypatch, row_kind, caplog
):
    r = recorder
    await stop_heartbeat(r)
    monkeypatch.setattr(_capture, "RENEW_SECONDS", 0)
    checked = 0
    lease = r.capture._lease

    async def check():
        nonlocal checked
        checked += 1
        if row_kind == "error":
            raise RuntimeError(SECRET)
        if checked > 1:
            raise TeachingRefused(TeachingReason.OWNERSHIP_LOST)

    monkeypatch.setattr(lease, "check", check)
    if row_kind == "missing":
        _capture.repo.active.return_value = None
    elif row_kind == "foreign":
        r.row.takeover_id = uuid4()
    elif row_kind == "expired":
        r.row.capture_ends_at = datetime.now(UTC) - timedelta(seconds=1)
    await r.capture._maintain()
    assert r.capture._lease is None
    assert r.pause.call_args.args[-1] == (
        TeachingReason.NATIVE_UNAVAILABLE
        if row_kind == "error"
        else TeachingReason.TIME_LIMIT
        if row_kind == "expired"
        else TeachingReason.OWNERSHIP_LOST
    )
    assert SECRET not in caplog.text


async def test_concurrent_close_between_heartbeat_wait_and_lease_check_is_harmless(
    recorder, monkeypatch
):
    r = recorder
    await stop_heartbeat(r)
    monkeypatch.setattr(_capture, "RENEW_SECONDS", 0)
    lease = r.capture._lease
    asyncio.get_running_loop().call_soon(setattr, r.capture, "_lease", None)
    await r.capture._maintain()
    await r.capture._maintain()
    await lease.close()


async def test_publish_without_live_owner_is_silent_and_missing_receipt_is_explicit(recorder):
    r = recorder
    r.emit.reset_mock()
    r.capture._session_id = None
    await r.capture._publish(None)
    event = r.emit.call_args.args[0]
    assert event.teaching_status == "paused" and event.teaching_session_id is None
    assert event.teaching_reason is None
    await r.capture.end()
    r.emit.reset_mock()
    await r.capture._publish(receipt(r.held))
    r.emit.assert_not_awaited()


async def test_automatic_hooks_use_the_same_guarded_owner_and_sanitize_later_events(recorder):
    r = recorder
    await r.capture.end()
    native = SimpleNamespace(
        begin=AsyncMock(),
        before=AsyncMock(return_value="prepared"),
        after=AsyncMock(),
        finish=AsyncMock(),
        redacting=True,
        origin=ORIGIN,
    )
    r.capture._refinement = native
    await r.capture.begin_task("owned-call", r.emit)
    native.begin.assert_awaited_once_with("owned-call", r.emit)
    action = Click(action="click", index=0)
    assert await r.capture.before_action(action, None) == "prepared"
    await r.capture.after_action(None)
    await r.capture.finish_task(completed=True)
    native.finish.assert_awaited_once_with(completed=True)
    event = r.capture.event(
        BrowserEvent(
            kind="browser_finished",
            call_id="owned-call",
            step=1,
            title=SECRET,
            detail=SECRET,
        )
    )
    assert event.url == ORIGIN and SECRET not in event.model_dump_json()
    await r.capture.protect()
    await r.capture.begin_task("later", r.emit)
    assert native.begin.await_count == 1


async def test_declined_optional_learning_does_not_restore_opaque_output_after_manual_capture(
    recorder,
):
    r = recorder
    await r.capture.end()
    native = SimpleNamespace(begin=AsyncMock(), finish=AsyncMock(), redacting=False)
    r.capture._refinement = native
    await r.capture.begin_task("unrecorded-call", r.emit)
    native.begin.assert_awaited_once_with("unrecorded-call", r.emit)
    event = r.capture.event(
        BrowserEvent(kind="browser_finished", call_id="unrecorded-call", step=1, title=SECRET)
    )
    assert SECRET not in event.model_dump_json()
