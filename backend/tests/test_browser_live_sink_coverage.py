"""The live-view sink routes events by whether a run view and a chat sink exist."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.agents.capabilities.browser_use._toolset import _live
from app.services import live_browse

pytestmark = pytest.mark.anyio
ORIGIN = "https://portal.example.test"


def _deps(chat: AsyncMock | None, *, with_run: bool) -> SimpleNamespace:
    return SimpleNamespace(
        browser_events=chat,
        run_id=uuid4() if with_run else None,
        organization_id=uuid4() if with_run else None,
        agent_id=uuid4(),
        user_id=str(uuid4()),
        audience=None,
    )


def _event(kind: str = "browser_frame", **fields: object) -> BrowserEvent:
    return BrowserEvent.model_validate({"kind": kind, "call_id": "call", "step": 0, **fields})


async def test_without_a_run_view_events_reach_only_the_chat_sink(monkeypatch) -> None:
    monkeypatch.setattr(live_browse, "available", lambda: False)
    publish = AsyncMock()
    monkeypatch.setattr(live_browse, "publish", publish)
    chat = AsyncMock(return_value=True)
    sink, _, run = await _live(_deps(chat, with_run=False), "call", "task")
    assert run is None
    event = _event()
    assert await sink(event) is True
    chat.assert_awaited_once_with(event)
    publish.assert_not_awaited()


async def test_without_a_run_view_or_chat_there_is_no_sink(monkeypatch) -> None:
    monkeypatch.setattr(live_browse, "available", lambda: False)
    sink, control, run = await _live(_deps(None, with_run=False), "call", "task")
    assert (sink, control, run) == (None, None, None)


async def test_protection_announced_with_a_run_view_and_no_chat_publishes_once(
    monkeypatch,
) -> None:
    monkeypatch.setattr(live_browse, "available", lambda: True)
    monkeypatch.setattr(live_browse, "open_view", AsyncMock())
    monkeypatch.setattr(live_browse, "has_viewers", AsyncMock(return_value=False))
    monkeypatch.setattr(live_browse, "publish", AsyncMock())
    protect_view = AsyncMock()
    monkeypatch.setattr(live_browse, "protect_view", protect_view)
    guard = BrowserOutputGuard()
    sink, _, run = await _live(_deps(None, with_run=True), "call", "task", lambda: guard)
    assert run is not None
    frame = _event(image=base64.b64encode(b"pixels").decode())
    assert await sink(frame) is False
    guard.protect(ORIGIN)
    await guard.announce()
    protect_view.assert_awaited_once()
    announced = protect_view.await_args.args[-1]
    assert announced.kind == "browser_protected"
    assert announced.image is None


async def test_a_protected_event_without_a_guard_is_published_and_sent_to_chat(
    monkeypatch,
) -> None:
    monkeypatch.setattr(live_browse, "available", lambda: True)
    monkeypatch.setattr(live_browse, "open_view", AsyncMock())
    publish = AsyncMock()
    monkeypatch.setattr(live_browse, "publish", publish)
    protect_view = AsyncMock()
    monkeypatch.setattr(live_browse, "protect_view", protect_view)
    chat = AsyncMock(return_value=True)
    sink, _, run = await _live(_deps(chat, with_run=True), "call", "task")
    event = _event("browser_protected", url=ORIGIN, output_protected=True)
    assert await sink(event) is True
    protect_view.assert_awaited_once_with(run, "call", event)
    chat.assert_awaited_once_with(event)
    publish.assert_not_awaited()


async def test_a_protected_event_without_a_guard_returns_true_without_chat(
    monkeypatch,
) -> None:
    monkeypatch.setattr(live_browse, "available", lambda: True)
    monkeypatch.setattr(live_browse, "open_view", AsyncMock())
    monkeypatch.setattr(live_browse, "publish", AsyncMock())
    protect_view = AsyncMock()
    monkeypatch.setattr(live_browse, "protect_view", protect_view)
    sink, _, run = await _live(_deps(None, with_run=True), "call", "task")
    event = _event("browser_protected", url=ORIGIN, output_protected=True)

    assert sink is not None and run is not None
    assert await sink(event) is True
    protect_view.assert_awaited_once_with(run, "call", event)
    live_browse.publish.assert_not_awaited()
