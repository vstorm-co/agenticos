"""The two recorders share one sticky credential-output boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.capabilities.browser_use import _toolset
from app.agents.capabilities.browser_use._protected import (
    PROTECTED_TEXT,
    PROTECTED_TITLE,
    BrowserOutputGuard,
)
from app.agents.capabilities.browser_use._teaching_capture import BrowserTeachingCapture
from app.core.browser_procedure_teaching import BrowserProcedureTeachingReason

pytestmark = pytest.mark.anyio


def _event() -> BrowserEvent:
    return BrowserEvent(
        kind="browser_step",
        call_id="call-1",
        step=2,
        url="https://private.example.test/?token=synthetic-secret",
        title="Synthetic private title",
        goal="Synthetic private goal",
        target="Synthetic private target",
        reason="Synthetic private reason",
        image="data:image/jpeg;base64,synthetic-image-secret",
        detail="Synthetic private detail",
    )


def _captures(*, simple_end=None):
    simple = SimpleNamespace(
        begin=AsyncMock(),
        before_input=AsyncMock(return_value=object()),
        after_input=AsyncMock(),
        failed_input=AsyncMock(),
        end=AsyncMock() if simple_end is None else simple_end,
    )
    procedure = SimpleNamespace(
        begin_task=AsyncMock(),
        before_action=AsyncMock(return_value=object()),
        after_action=AsyncMock(),
        finish_task=AsyncMock(),
        begin=AsyncMock(return_value=uuid4()),
        before_input=AsyncMock(return_value=object()),
        after_input=AsyncMock(),
        failed_input=AsyncMock(),
        end=AsyncMock(),
        protect=AsyncMock(),
        close=AsyncMock(),
        event=Mock(side_effect=lambda event: event),
    )
    return simple, procedure


def _assert_redacted(event: BrowserEvent, *, url: str) -> None:
    assert event.output_protected is True
    assert event.url == url
    assert event.title == PROTECTED_TITLE
    assert event.reason == PROTECTED_TEXT
    assert event.goal is None
    assert event.target is None
    assert event.image is None
    assert event.detail is None
    assert "Synthetic private" not in event.model_dump_json()
    assert "synthetic-secret" not in event.model_dump_json()
    assert "synthetic-image-secret" not in event.model_dump_json()


async def test_begin_with_socket_keeps_the_simple_hold_and_starts_rich_capture() -> None:
    simple, procedure = _captures()
    guard = BrowserOutputGuard()
    composite = BrowserTeachingCapture(simple, procedure, guard)
    emit = AsyncMock(return_value=True)
    connection_id = uuid4()

    takeover_id = await composite.begin(
        "call-1",
        "stale-user",
        connection_id=connection_id,
        user_id="current-user",
        emit=emit,
    )

    assert takeover_id is not None
    simple.begin.assert_awaited_once_with("call-1", "current-user")
    procedure.begin.assert_awaited_once_with(
        call_id="call-1",
        connection_id=connection_id,
        user_id="current-user",
        emit=emit,
    )


@pytest.mark.security
async def test_protect_closes_admission_before_cleanup_and_redacts_the_gap() -> None:
    cleanup_started = asyncio.Event()
    finish_cleanup = asyncio.Event()

    async def blocked_end() -> None:
        cleanup_started.set()
        await finish_cleanup.wait()

    simple, procedure = _captures(simple_end=blocked_end)
    guard = BrowserOutputGuard()
    composite = BrowserTeachingCapture(simple, procedure, guard)
    protect_task = asyncio.create_task(composite.protect())
    await cleanup_started.wait()

    # The page guard is activated by the caller after recorder cleanup. During
    # this await, the composite's sticky flag must already reject new work and
    # reconstruct browser output from the protected allowlist.
    assert not guard.active
    assert await composite.begin("call-2", "user", emit=AsyncMock()) is None
    assert (
        await composite.before_input(
            BrowserCommand(type="navigate", by_user_id="user", control_sequence=1)
        )
        is None
    )
    await composite.after_input(object())
    await composite.failed_input()
    await composite.begin_task("call-2", AsyncMock())
    assert await composite.before_action("click", None) is None
    await composite.after_action(None)
    await composite.finish_task(completed=True)
    _assert_redacted(await composite.event(_event()), url="about:blank")

    simple.begin.assert_not_awaited()
    simple.before_input.assert_not_awaited()
    procedure.begin.assert_not_awaited()
    procedure.before_input.assert_not_awaited()
    procedure.before_action.assert_not_awaited()
    procedure.protect.assert_not_awaited()

    finish_cleanup.set()
    await protect_task
    procedure.protect.assert_awaited_once()


@pytest.mark.security
async def test_already_protected_page_blocks_both_recorders_and_redacts_events() -> None:
    simple, procedure = _captures()
    guard = BrowserOutputGuard()
    guard.protect("https://safe.example.test")
    composite = BrowserTeachingCapture(simple, procedure, guard)

    assert await composite.begin("call-1", "user", emit=AsyncMock()) is None
    assert (
        await composite.before_input(
            BrowserCommand(type="navigate", by_user_id="user", control_sequence=1)
        )
        is None
    )
    await composite.begin_task("call-1", AsyncMock())
    assert await composite.before_action("click", None) is None
    _assert_redacted(await composite.event(_event()), url="https://safe.example.test")

    simple.begin.assert_not_awaited()
    simple.before_input.assert_not_awaited()
    procedure.begin.assert_not_awaited()
    procedure.before_input.assert_not_awaited()
    procedure.before_action.assert_not_awaited()
    procedure.event.assert_not_called()


@pytest.mark.security
@pytest.mark.parametrize("failing", ["simple", "procedure"])
async def test_recorder_failure_is_private_and_does_not_disable_the_other(
    failing: str, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "synthetic-capture-error-secret"
    simple, procedure = _captures()
    if failing == "simple":
        simple.begin.side_effect = RuntimeError(secret)
    else:
        procedure.begin.side_effect = RuntimeError(secret)
    composite = BrowserTeachingCapture(simple, procedure, BrowserOutputGuard())

    await composite.begin("call-1", "user", emit=AsyncMock())
    prepared = await composite.before_input(
        BrowserCommand(type="navigate", by_user_id="user", control_sequence=1)
    )
    assert prepared is not None
    await composite.after_input(prepared)

    assert secret not in caplog.text
    if failing == "simple":
        simple.begin.assert_awaited_once()
        simple.end.assert_awaited_once()
        simple.before_input.assert_not_awaited()
        simple.after_input.assert_not_awaited()
        procedure.begin.assert_awaited_once()
        procedure.before_input.assert_awaited_once()
        procedure.after_input.assert_awaited_once()
    else:
        simple.begin.assert_awaited_once()
        simple.before_input.assert_awaited_once()
        simple.after_input.assert_awaited_once()
        procedure.begin.assert_awaited_once()
        procedure.end.assert_awaited_once()
        procedure.before_input.assert_not_awaited()
        procedure.after_input.assert_not_awaited()


@pytest.mark.security
async def test_rich_event_failure_protects_output_and_stops_both_recorders(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "synthetic-event-transform-secret"
    simple, procedure = _captures()
    procedure.event.side_effect = RuntimeError(secret)
    guard = BrowserOutputGuard()
    composite = BrowserTeachingCapture(simple, procedure, guard)
    chat = AsyncMock(return_value=True)
    monkeypatch.setattr(_toolset.live_browse, "available", lambda: False)
    deps = SimpleNamespace(browser_events=chat, run_id=None, organization_id=None)
    sink, control, run = await _toolset._live(
        deps,
        "call-1",
        "synthetic task",
        get_guard=lambda: guard,
        get_teaching=lambda: composite,
    )
    assert sink is not None and control is None and run is None

    cleanup_finished = asyncio.Event()
    status = BrowserEvent(
        kind="browser_procedure_teaching",
        call_id="call-1",
        step=2,
        run_id="synthetic-run",
        teaching_session_id=uuid4(),
        teaching_status="discarded",
        teaching_revision=2,
        teaching_reason=BrowserProcedureTeachingReason.NATIVE_UNAVAILABLE,
    )

    async def emit_final_status() -> None:
        assert sink is not None
        await sink(status)
        cleanup_finished.set()

    procedure.end.side_effect = emit_final_status

    await composite.begin("call-1", "user", connection_id=uuid4(), user_id="user", emit=sink)

    assert await asyncio.wait_for(sink(_event()), timeout=2)

    events = [call.args[0] for call in chat.await_args_list]
    assert [event.kind for event in events] == ["browser_procedure_teaching", "browser_step"]
    for event in events:
        _assert_redacted(event, url="about:blank")
    simple.end.assert_awaited_once()
    procedure.end.assert_awaited_once()
    assert cleanup_finished.is_set()
    assert secret not in caplog.text
    assert await composite.before_input(BrowserCommand(type="reload")) is None
    assert await composite.before_action("click", None) is None
    simple.before_input.assert_not_awaited()
    procedure.before_input.assert_not_awaited()
    procedure.before_action.assert_not_awaited()
