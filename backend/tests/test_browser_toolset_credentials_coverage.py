"""Saved-credential browser tools refuse safely, and a continuation tab is admitted only when safe."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.browser_use import _toolset as browser
from app.agents.capabilities.browser_use._page import CdpPage, PagePolicy
from app.agents.capabilities.browser_use._route import BrowserRoute
from app.agents.deps import AgentDeps
from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused
from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from app.services import live_browse
from tests.test_browser_use import DONE_ARGS, _browsing_model, _policy, _snapshot

pytestmark = pytest.mark.anyio
ORIGIN = "https://portal.example.test"
UNAVAILABLE = "Saved credential filling is unavailable in this browser session."
FILL_ARGS = {
    "secret_id": str(uuid4()),
    "authorization_generation": str(uuid4()),
    "selection": {"fields": [{"field": "password", "element_id": 0}]},
}


class _Harness:
    def __init__(self, monkeypatch, *, route: BrowserRoute | None = None) -> None:
        self.redis: object | None = object()
        self.controller_kwargs: list[dict[str, object]] = []
        self.controller = SimpleNamespace(
            alive=True,
            ctx=None,
            redis=self.redis,
            identity=SimpleNamespace(run_id=uuid4(), call_id="open", tab_id="main"),
            request=AsyncMock(),
            wait=AsyncMock(),
            close=AsyncMock(),
        )
        monkeypatch.setattr(live_browse, "available", lambda: True)
        monkeypatch.setattr(live_browse, "open_view", AsyncMock())
        monkeypatch.setattr(live_browse, "has_viewers", AsyncMock(return_value=False))
        monkeypatch.setattr(live_browse, "publish", AsyncMock())
        monkeypatch.setattr(live_browse, "protect_view", AsyncMock())
        monkeypatch.setattr(live_browse, "credential_redis", lambda: self.redis)
        monkeypatch.setattr(browser, "recheck", AsyncMock(return_value=route))

        async def create(**kwargs):
            self.controller_kwargs.append(kwargs)
            return self.controller

        monkeypatch.setattr(browser.BrowserCredentialController, "create", create)

        @asynccontextmanager
        async def database():
            yield None

        monkeypatch.setattr(browser, "get_db_context", database)

        @asynccontextmanager
        async def restore(*args):
            yield None

        monkeypatch.setattr(browser, "protected_restore", restore)
        self.page = CdpPage(MagicMock(), str(uuid4()), PagePolicy(None, 60, 1024))
        self.page.snapshot = AsyncMock(return_value=_snapshot(text="Synthetic page"))
        self.page.location = AsyncMock(return_value=(ORIGIN, "Synthetic page"))

        @asynccontextmanager
        async def open_page(**kwargs):
            yield self.page

        self.toolset = browser.build_toolset(
            cdp_url="http://browser:9222",
            page_policy=PagePolicy(None, 60, 1024),
            loop_policy=_policy(),
            page_factory=open_page,
            credential_ids=(uuid4(),),
            route=route,
        )
        self.ctx = RunContext(
            deps=AgentDeps(
                run_id=uuid4(),
                organization_id=uuid4(),
                agent_id=uuid4(),
                browser_events=AsyncMock(return_value=True),
            ),
            model=_browsing_model(DONE_ARGS),
            usage=RunUsage(),
            tool_call_id="open",
        )

    async def invoke(self, name: str, args: dict[str, object] | None = None) -> str:
        tools = await self.toolset.get_tools(self.ctx)
        return str(await self.toolset.call_tool(name, args or {}, self.ctx, tools[name]))

    async def open(self) -> None:
        await self.invoke("browser_open", {"url": ORIGIN})
        assert self.controller_kwargs


async def test_credential_tools_need_an_open_tab(monkeypatch) -> None:
    h = _Harness(monkeypatch)
    async with h.toolset:
        assert await h.invoke("browser_credential_options") == browser.NO_TAB
        assert await h.invoke("browser_fill_credential", FILL_ARGS) == browser.NO_TAB
    h.controller.request.assert_not_awaited()


async def test_credential_tools_refuse_when_the_controller_is_not_alive(monkeypatch) -> None:
    h = _Harness(monkeypatch)
    h.controller.alive = False
    async with h.toolset:
        await h.open()
        assert await h.invoke("browser_credential_options") == UNAVAILABLE
        assert (
            await h.invoke("browser_fill_credential", FILL_ARGS)
            == "Browser credential request refused: live_browser_required."
        )
    h.controller.request.assert_not_awaited()


async def test_a_refused_eligibility_lookup_gives_the_fixed_refusal(monkeypatch) -> None:
    h = _Harness(monkeypatch)
    refusal = AsyncMock(side_effect=BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST))
    monkeypatch.setattr(browser.BrowserCredentialPlanService, "eligible", refusal)
    async with h.toolset:
        await h.open()
        assert await h.invoke("browser_credential_options") == UNAVAILABLE
    refusal.assert_awaited_once()


async def test_a_refused_fill_request_names_only_its_reason(monkeypatch) -> None:
    h = _Harness(monkeypatch)
    h.controller.request.side_effect = BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED)
    async with h.toolset:
        await h.open()
        assert (
            await h.invoke("browser_fill_credential", FILL_ARGS)
            == "Browser credential request refused: document_changed."
        )
    h.controller.wait.assert_not_awaited()


async def test_protecting_the_page_also_stops_its_teaching_capture(monkeypatch) -> None:
    h = _Harness(monkeypatch)
    async with h.toolset:
        await h.open()
        teaching = SimpleNamespace(protect=AsyncMock(), close=AsyncMock())
        assert h.toolset.session is not None
        h.toolset.session.teaching = teaching
        await h.controller_kwargs[0]["protect"](ORIGIN)
        teaching.protect.assert_awaited_once()
        assert h.page.output_guard.active
        h.toolset.session.teaching = None


@pytest.mark.parametrize("case", ["duplicate_tab", "tab_limit", "hosted", "no_redis"])
async def test_a_continuation_tab_is_refused_before_anything_opens(monkeypatch, case) -> None:
    hosted = BrowserRoute(
        remote_url=SecretStr("wss://hosted.example.test/?key=secret"),
        remote_address="wss://hosted.example.test/",
    )
    h = _Harness(monkeypatch, route=hosted if case == "hosted" else None)
    async with h.toolset:
        await h.open()
        continue_session = h.controller_kwargs[0]["continue_session"]
        claim = SimpleNamespace(tab_id="main" if case == "duplicate_tab" else "other")
        if case == "tab_limit":
            monkeypatch.setattr(h.toolset, "sessions", lambda: dict.fromkeys(range(8)))
        if case == "no_redis":
            h.redis = None
        expected = (
            BrowserContinuationReason.DESTINATION_REFUSED
            if case == "hosted"
            else BrowserContinuationReason.NOT_AVAILABLE
        )
        with pytest.raises(BrowserContinuationRefused) as refused:
            async with continue_session(claim, SimpleNamespace()):
                pytest.fail("a refused continuation must not run its body")
        assert refused.value.reason == expected
