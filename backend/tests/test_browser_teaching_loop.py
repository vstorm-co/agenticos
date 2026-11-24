"""The browse loop tells an attached teaching capture what each action did, and when one was refused."""

from typing import Any, cast

import pytest

from app.agents.capabilities.browser_use._decision import Navigate
from app.agents.capabilities.browser_use._loop import BrowseSession
from tests.test_browser_use import DONE, _browse, _decider, _FakePage, _step

pytestmark = pytest.mark.anyio


class _Teaching:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def begin_task(self, *_args: Any) -> None:
        self.calls.append(("begin_task", None))

    async def before_action(self, *_args: Any) -> str:
        self.calls.append(("before_action", None))
        return "prepared"

    async def after_action(self, prepared: object) -> None:
        self.calls.append(("after_action", prepared))

    async def finish_task(self, **kwargs: Any) -> None:
        self.calls.append(("finish_task", kwargs))


def _session(page: _FakePage, teaching: _Teaching) -> BrowseSession:
    session = BrowseSession(page=page)
    session.teaching = cast(Any, teaching)
    return session


GO = _step(Navigate(action="navigate", url="https://example.test/pricing"))


async def test_an_action_that_happened_is_reported_to_the_capture_as_prepared() -> None:
    teaching = _Teaching()
    await _browse(_session(_FakePage(), teaching), _decider(GO, DONE))
    assert ("before_action", None) in teaching.calls
    assert ("after_action", "prepared") in teaching.calls


async def test_a_refused_action_ends_the_captured_task_as_not_completed() -> None:
    teaching = _Teaching()
    await _browse(_session(_FakePage(refuse="the page moved"), teaching), _decider(GO, DONE))
    assert ("finish_task", {"completed": False}) in teaching.calls
    assert ("after_action", None) in teaching.calls
    assert ("after_action", "prepared") not in teaching.calls
