"""A person's hold on the browser, with teaching attached: every way it can end releases the capture."""

from typing import Any, cast

import pytest

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.agents.capabilities.browser_use import _loop
from app.agents.capabilities.browser_use._loop import BrowseSession
from tests.test_browser_use import _Control, _FakePage

pytestmark = pytest.mark.anyio


class _Teaching:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def begin(self, **_kwargs: Any) -> None:
        self.calls.append("begin")

    async def before_input(self, _command: BrowserCommand) -> str:
        self.calls.append("before_input")
        return "prepared"

    async def after_input(self, prepared: object) -> None:
        self.calls.append(f"after_input:{prepared}")

    async def failed_input(self) -> None:
        self.calls.append("failed_input")

    async def end(self) -> None:
        self.calls.append("end")


def _session(teaching: _Teaching) -> BrowseSession:
    session = BrowseSession(page=_FakePage())
    session.teaching = cast(Any, teaching)
    return session


async def _hold(session: BrowseSession, control: _Control, emit: Any) -> None:
    await _loop.held(
        session, control, emit, call_id="c-1", by="Ada", by_user_id="u-1", remember=None
    )


async def test_a_hold_whose_announcement_cannot_be_sent_ends_the_capture_and_raises() -> None:
    teaching = _Teaching()

    async def emit(_event: BrowserEvent) -> bool:
        raise ConnectionError("socket closed")

    with pytest.raises(ConnectionError):
        await _hold(_session(teaching), _Control(), emit)
    assert teaching.calls == ["begin", "end"]


async def test_losing_control_ends_the_hold_and_the_capture() -> None:
    teaching = _Teaching()
    events: list[BrowserEvent] = []

    async def emit(event: BrowserEvent) -> bool:
        events.append(event)
        return True

    lost = BrowserCommand(type="control_lost", by_user_id="u-1")
    await _hold(_session(teaching), _Control(lost), emit)
    assert teaching.calls == ["begin", "end"]
    assert [event.kind for event in events][-1] == "browser_released"


async def test_a_hold_without_teaching_whose_announcement_fails_still_raises() -> None:
    async def emit(_event: BrowserEvent) -> bool:
        raise ConnectionError("socket closed")

    session = BrowseSession(page=_FakePage())
    assert session.teaching is None
    with pytest.raises(ConnectionError):
        await _loop.held(
            session, _Control(), emit, call_id="c-1", by="Ada", by_user_id="u-1", remember=None
        )
