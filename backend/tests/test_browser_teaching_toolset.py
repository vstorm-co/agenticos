"""The toolset attaches teaching capture to the provisioned browser and releases it when the tab leaves.

Capture exists only on the deployment's own CDP browser, never on a hosted
endpoint; a tab that stops being the one in front ends its capture.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.capabilities.browser_use import _toolset
from app.agents.capabilities.browser_use._page import CdpPage, PagePolicy
from app.core.config import settings
from app.services import live_browse
from tests.test_browser_use import _call, _element, _Opener, _policy, _snapshot
from tests.test_browser_use import _toolset as build

pytestmark = pytest.mark.anyio

CDP = "http://browser:9222"


class _Capture:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def end(self) -> None:
        self.calls.append("end")

    async def close(self) -> None:
        self.calls.append("close")

    async def begin_task(self, *_args: Any) -> None:
        self.calls.append("begin_task")

    async def before_action(self, *_args: Any) -> None:
        return None

    async def after_action(self, *_args: Any) -> None:
        return None

    async def finish_task(self, **_kwargs: Any) -> None:
        self.calls.append("finish_task")


class _CdpOpener(_Opener):
    """Hands out a real CDP page object over a mock protocol client, as the provisioned browser does."""

    def __init__(self) -> None:
        super().__init__()
        self.cdp = CdpPage(MagicMock(), "session-1", PagePolicy(None, 60, 1024))
        self.cdp.snapshot = AsyncMock(return_value=_snapshot(_element(0)))  # type: ignore[method-assign]
        self.cdp.location = AsyncMock(return_value=("https://portal.example.com/", "Portal"))  # type: ignore[method-assign]
        self.cdp.screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        self.cdp.read = AsyncMock(return_value="the page text")  # type: ignore[method-assign]

    @asynccontextmanager
    async def __call__(self, **kwargs: Any) -> AsyncGenerator[Any]:
        self.opened.append(kwargs)
        yield self.cdp


async def test_parking_a_tab_ends_its_teaching_capture() -> None:
    async with build(_Opener()) as toolset:
        await _call(toolset)
        session = toolset.session
        assert session is not None
        capture = _Capture()
        session.teaching = cast(Any, capture)
        await toolset.park()
        assert capture.calls == ["end"]
        assert toolset.session is None
        assert toolset.parked[toolset.tab_id][0] is session


async def test_parking_a_tab_with_no_capture_changes_nothing_else() -> None:
    async with build(_Opener()) as toolset:
        await _call(toolset)
        assert toolset.session is not None and toolset.session.teaching is None
        await toolset.park()
        assert toolset.session is None


@pytest.fixture
def provisioned(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> _Capture:
        created.append(kwargs)
        return _Capture()

    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", CDP)
    monkeypatch.setattr(live_browse, "credential_redis", lambda: SimpleNamespace())
    monkeypatch.setattr(_toolset.ProcedureCapture, "create", create)
    monkeypatch.setattr(_toolset.browser_teaching, "attach", lambda *_a, **_k: None)
    return created


async def test_a_provisioned_tab_gets_a_procedure_capture_when_teaching_is_allowed(
    provisioned: list[dict[str, Any]],
) -> None:
    opener = _CdpOpener()
    toolset = _toolset.build_toolset(
        cdp_url=CDP,
        page_policy=PagePolicy(None, 60, 1024),
        loop_policy=_policy(),
        page_factory=opener,
        allow_teaching=True,
    )
    async with toolset:
        await _call(toolset)
        session = toolset.session
        assert session is not None and session.teaching is not None
        assert len(provisioned) == 1
        assert provisioned[0]["guard"] is opener.cdp.output_guard


async def test_a_tab_on_another_browser_or_without_teaching_allowed_gets_no_capture(
    provisioned: list[dict[str, Any]],
) -> None:
    for allow, cdp_url in ((False, CDP), (True, "http://elsewhere:9222")):
        opener = _CdpOpener()
        toolset = _toolset.build_toolset(
            cdp_url=cdp_url,
            page_policy=PagePolicy(None, 60, 1024),
            loop_policy=_policy(),
            page_factory=opener,
            allow_teaching=allow,
        )
        async with toolset:
            await _call(toolset)
            assert toolset.session is not None and toolset.session.teaching is None
    assert provisioned == []
