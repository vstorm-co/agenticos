"""Accepted native actions carry structural provenance without retaining model inputs."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.capabilities.browser_use import _loop
from app.agents.capabilities.browser_use._decision import (
    Click,
    GoBack,
    Navigate,
    Scroll,
    Select,
    TypeText,
    Wait,
)
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingObservation,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
)
from app.core.permissions import AuthContext
from app.services.browser_procedure_teaching import _refinement_capture as capture
from app.services.browser_procedure_teaching._lease import BrowserProcedureTeachingIdentity
from tests.test_browser_procedure_teaching_capture import receipt
from tests.test_browser_procedure_teaching_contracts import ORIGIN, SECRET, TARGET
from tests.test_browser_procedure_teaching_native import identity

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_a_detached_sink_receives_no_late_teaching_event(recorder):
    r = recorder
    r.recorder._emit = None
    r.emit.reset_mock()
    await r.recorder._publish(r.data)
    r.emit.assert_not_awaited()


async def test_a_refused_final_observation_cannot_claim_browser_completion(recorder):
    r = recorder
    r.page.observe.side_effect = BrowserProcedureTeachingRefused(
        BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE
    )
    await r.recorder.finish(completed=True)
    assert r.finish.await_args.kwargs == {
        "completed": False,
        "reason": BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE,
    }


async def test_a_deleted_recording_has_no_final_success_event(recorder):
    r = recorder
    r.finish.return_value = None
    r.emit.reset_mock()
    await r.recorder.finish(completed=False)
    r.emit.assert_not_awaited()


@pytest.fixture
async def recorder(monkeypatch):
    held = identity()
    ctx = AuthContext(user_id=held.user_id, organization_id=held.organization_id, role="member")
    data = receipt(held, source="refinement")
    page = SimpleNamespace(
        observe=AsyncMock(
            return_value=BrowserProcedureTeachingObservation(origin=ORIGIN, target=TARGET)
        )
    )
    guard, emit, locate = (
        BrowserOutputGuard(),
        AsyncMock(return_value=True),
        AsyncMock(return_value=(30, 40)),
    )
    start, authorize, append, finish = (
        AsyncMock(return_value=data),
        AsyncMock(),
        AsyncMock(return_value=data),
        AsyncMock(return_value=data.model_copy(update={"status": "review"})),
    )
    db = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield db

    monkeypatch.setattr(capture, "get_db_context", transaction)
    monkeypatch.setattr(capture._refinement, "start", start)
    monkeypatch.setattr(capture._refinement, "authorize_capture", authorize)
    monkeypatch.setattr(capture._refinement, "append", append)
    monkeypatch.setattr(capture._refinement, "finish", finish)
    recorder = capture.BrowserProcedureTeachingRefinementCapture(
        context=ctx,
        identity=BrowserProcedureTeachingIdentity.model_validate(
            held.model_dump(exclude={"takeover_id", "connection_id"})
        ),
        page=page,
        guard=guard,
        step=lambda: 4,
        locate=locate,
    )
    await recorder.begin("owned-task", emit)
    try:
        yield SimpleNamespace(
            recorder=recorder,
            data=data,
            page=page,
            guard=guard,
            emit=emit,
            locate=locate,
            start=start,
            authorize=authorize,
            append=append,
            finish=finish,
        )
    finally:
        await recorder.finish(completed=False)


@pytest.mark.parametrize(
    ("action", "kind"),
    [
        (Click(action="click", index=0), "click"),
        (TypeText(action="type", index=0, text=SECRET), "input_parameter"),
        (Select(action="select", index=0, option=SECRET), "select"),
        (Scroll(action="scroll", direction="down"), "scroll"),
        (Navigate(action="navigate", url=ORIGIN + "?token=" + SECRET), "navigate"),
        (GoBack(action="back"), "navigate"),
    ],
)
async def test_action_values_and_urls_never_reach_the_structural_row(recorder, action, kind):
    r = recorder
    prepared = await r.recorder.before(action, object())
    assert prepared.action == kind and SECRET not in repr(prepared)
    await r.recorder.after(prepared)
    r.authorize.assert_awaited_once()
    assert SECRET not in repr(r.append.call_args)
    assert r.append.call_args.kwargs["action"] == kind
    assert all(SECRET not in call.args[0].model_dump_json() for call in r.emit.call_args_list)


async def test_wait_and_missing_recording_do_not_invent_actions(recorder):
    r = recorder
    assert await r.recorder.before(Wait(action="wait"), None) is None
    await r.recorder.after(None)
    await r.recorder.finish(completed=False)
    assert await r.recorder.before(Click(action="click", index=0), object()) is None
    await r.recorder.after(None)
    r.append.assert_not_awaited()


@pytest.mark.parametrize("point", ["before", "after", "finish"])
async def test_credential_protection_stops_capture_before_any_further_read(recorder, point):
    r = recorder
    prepared = await r.recorder.before(Click(action="click", index=0), object())
    r.page.observe.reset_mock()
    r.guard.protect(ORIGIN)
    if point == "before":
        assert await r.recorder.before(Click(action="click", index=0), object()) is None
    elif point == "after":
        await r.recorder.after(prepared)
    else:
        await r.recorder.finish(completed=True)
    assert r.finish.call_args.kwargs == {
        "completed": False,
        "reason": BrowserProcedureTeachingReason.PROTECTED,
    }
    r.page.observe.assert_not_awaited()
    r.append.assert_not_awaited()


@pytest.mark.parametrize("point", ["after", "finish"])
async def test_redirect_cannot_expand_the_saved_origin(recorder, point):
    r = recorder
    prepared = await r.recorder.before(Click(action="click", index=0), object())
    r.page.observe.return_value = BrowserProcedureTeachingObservation(
        origin="https://different.example.test"
    )
    if point == "after":
        await r.recorder.after(prepared)
    else:
        await r.recorder.finish(completed=True)
    assert r.finish.call_args.kwargs == {
        "completed": False,
        "reason": BrowserProcedureTeachingReason.ORIGIN_REFUSED,
    }
    r.append.assert_not_awaited()


@pytest.mark.parametrize(
    "point", ["before_refused", "before_error", "after_refused", "after_error", "finish"]
)
async def test_native_or_authority_errors_are_fixed_and_not_retried(recorder, point, caplog):
    r = recorder
    error = (
        BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.AUTHORITY_CHANGED)
        if point.endswith("refused")
        else RuntimeError(SECRET)
    )
    if point.startswith("before"):
        r.authorize.side_effect = error
        assert await r.recorder.before(Click(action="click", index=0), object()) is None
    elif point.startswith("after"):
        prepared = await r.recorder.before(Click(action="click", index=0), object())
        r.append.side_effect = error
        await r.recorder.after(prepared)
    else:
        r.finish.side_effect = error
        await r.recorder.finish(completed=True)
    assert r.recorder._session_id is None
    count = r.finish.await_count
    await r.recorder.finish(completed=True)
    assert r.finish.await_count == count
    assert SECRET not in caplog.text


async def test_authentication_or_capture_limit_discards_automatic_suggestion(recorder):
    r = recorder
    prepared = await r.recorder.before(TypeText(action="type", index=0, text=SECRET), object())
    r.append.return_value = r.data.model_copy(
        update={"status": "paused", "reason_code": BrowserProcedureTeachingReason.AUTHENTICATION}
    )
    await r.recorder.after(prepared)
    assert r.finish.call_args.kwargs == {
        "completed": False,
        "reason": BrowserProcedureTeachingReason.AUTHENTICATION,
    }


async def test_cancelled_native_read_propagates_and_does_not_append(recorder):
    r = recorder
    r.locate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await r.recorder.before(TypeText(action="type", index=0, text=SECRET), object())
    r.append.assert_not_awaited()
    await r.recorder.finish(completed=False)
    assert not r.finish.call_args.kwargs["completed"]


async def test_missing_target_discards_without_guessing_coordinates(recorder):
    r = recorder
    assert await r.recorder.before(Click(action="click", index=7), None) is None
    r.locate.assert_not_awaited()
    assert not r.finish.call_args.kwargs["completed"]


@pytest.mark.parametrize("change", ["guard", "locator", "sink", "choice", "refused", "error"])
async def test_admission_refuses_missing_opt_in_or_supported_live_page(recorder, change, caplog):
    r = recorder
    await r.recorder.finish(completed=False)
    r.start.reset_mock()
    emit = r.emit
    if change == "guard":
        r.guard.protect(ORIGIN)
    elif change == "locator":
        r.recorder.locate = None
    elif change == "sink":
        emit = None
    elif change == "choice":
        r.start.return_value = None
    else:
        r.start.side_effect = (
            BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.OPTED_OUT)
            if change == "refused"
            else RuntimeError(SECRET)
        )
    await r.recorder.begin("another-call", emit)
    assert r.recorder._session_id is None
    if change in {"guard", "locator", "sink"}:
        r.start.assert_not_awaited()
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "outcome", ["done", "blocked", "failed", "exhausted", "cancelled", "error"]
)
async def test_loop_finally_reports_only_a_done_browser_result(monkeypatch, outcome):
    teaching = AsyncMock()
    session = SimpleNamespace(teaching=teaching)
    drive = AsyncMock()
    if outcome == "cancelled":
        drive.side_effect = asyncio.CancelledError()
    elif outcome == "error":
        drive.side_effect = RuntimeError("Synthetic stopped browse")
    else:
        drive.return_value = _loop.BrowseResult(outcome, "done", "page", 1)
    monkeypatch.setattr(_loop, "_drive", drive)

    async def run():
        return await _loop.run_browse(
            task="Synthetic task",
            session=session,
            decide=AsyncMock(),
            policy=_loop.LoopPolicy(max_steps=1, preview=False),
            call_id="owned-call",
        )

    if outcome in {"cancelled", "error"}:
        with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else RuntimeError):
            await run()
    else:
        assert (await run()).outcome == outcome
    teaching.begin_task.assert_awaited_once_with("owned-call", None)
    teaching.finish_task.assert_awaited_once_with(completed=outcome == "done")


@pytest.mark.parametrize("refused", [False, True])
async def test_real_loop_places_capture_after_the_native_action_and_settle(refused):
    from tests.test_browser_use import DONE, _decider, _FakePage, _step

    page = _FakePage(refuse="Synthetic stale page" if refused else None)
    teaching = AsyncMock()
    actions = []
    prepared = object()

    async def before(action, element):
        actions.append(("before", tuple(page.done)))
        return prepared

    async def after(value):
        actions.append(("after", tuple(page.done)))

    teaching.before_action.side_effect = before
    teaching.after_action.side_effect = after
    result = await _loop.run_browse(
        task="Synthetic navigate",
        session=_loop.BrowseSession(page=page, teaching=teaching),
        decide=_decider(_step(Navigate(action="navigate", url=ORIGIN)), DONE),
        policy=_loop.LoopPolicy(max_steps=3, preview=False),
        call_id="owned-task",
    )
    assert result.outcome == "done"
    assert actions[0] == ("before", ())
    assert actions[1][0] == "after"
    if refused:
        assert actions[1][1] == ()
        teaching.after_action.assert_awaited_once_with(None)
        assert teaching.finish_task.await_args_list[0].kwargs == {"completed": False}
    else:
        assert actions[1][1] == ("navigate:" + ORIGIN,)
        teaching.after_action.assert_awaited_once_with(prepared)
