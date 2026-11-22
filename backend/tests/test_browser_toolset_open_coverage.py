"""Opening a browser tab with saved credentials and checkpointing tabs across a conversation."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.browser_use import _sessions
from app.agents.capabilities.browser_use import _toolset as browser
from app.agents.capabilities.browser_use._page import CdpPage, PagePolicy
from app.agents.deps import AgentDeps, RunAudience
from app.services import browser_sign_in
from tests.test_browser_use import DONE_ARGS, _browsing_model, _policy

pytestmark = pytest.mark.anyio
ORIGIN = "https://portal.example.test"
UNAVAILABLE = "The protected saved session is unavailable for this run or current access."


def _cdp_page(*, protected: bool) -> CdpPage:
    page = CdpPage(MagicMock(), str(uuid4()), PagePolicy(None, 60, 1024))
    if protected:
        page.protect_credentials(ORIGIN)
    page.capture_sign_in = AsyncMock(return_value=None)
    page.snapshot = AsyncMock(side_effect=page.output_guard.snapshot)
    page.location = AsyncMock(
        side_effect=page.output_guard.location if protected else None,
        return_value=(ORIGIN + "/", "Portal"),
    )
    return page


class _Pages:
    def __init__(self, page: CdpPage) -> None:
        self.page = page
        self.options: list[dict[str, object]] = []
        self.closed = 0

    @asynccontextmanager
    async def __call__(self, **kwargs: object):
        self.options.append(kwargs)
        try:
            yield self.page
        finally:
            self.closed += 1


def _signed_in_deps() -> AgentDeps:
    owner = uuid4()
    return AgentDeps(
        user_id=str(owner),
        organization_id=uuid4(),
        agent_id=uuid4(),
        conversation_id=uuid4(),
        run_id=uuid4(),
        audience=RunAudience(user_id=owner, browses_signed_in=True),
    )


def _build(pages: _Pages, *, credentials: bool):
    return browser.build_toolset(
        cdp_url="http://browser:9222",
        page_policy=PagePolicy(None, 60, 1024),
        loop_policy=_policy(),
        page_factory=pages,
        credential_ids=(uuid4(),) if credentials else (),
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(
        deps=deps, model=_browsing_model(DONE_ARGS), usage=RunUsage(), tool_call_id="open"
    )


async def _open(toolset, deps: AgentDeps, url: str) -> str:
    ctx = _ctx(deps)
    tools = await toolset.get_tools(ctx)
    return str(await toolset.call_tool("browser_open", {"url": url}, ctx, tools["browser_open"]))


@pytest.fixture(autouse=True)
def _no_saved_state(monkeypatch) -> None:
    monkeypatch.setattr(browser_sign_in, "load_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(_sessions, "save", AsyncMock())
    monkeypatch.setattr(browser.live_browse, "credential_redis", lambda: None)


async def test_checkpoint_leaves_a_protected_tab_out_of_the_saved_browser() -> None:
    pages = _Pages(_cdp_page(protected=True))
    toolset = _build(pages, credentials=False)
    async with toolset:
        await _open(toolset, _signed_in_deps(), ORIGIN)
        assert toolset.checkpoint is not None
        await toolset.checkpoint()
    saved = [call.args[2] for call in _sessions.save.await_args_list]
    assert saved and all(tabs == [] for tabs in saved)
    pages.page.capture_sign_in.assert_not_awaited()


async def test_an_unusable_origin_opens_without_a_protected_restore(monkeypatch) -> None:
    restore = MagicMock()
    monkeypatch.setattr(browser, "protected_restore", restore)
    pages = _Pages(_cdp_page(protected=False))
    toolset = _build(pages, credentials=True)
    async with toolset:
        await _open(toolset, _signed_in_deps(), ORIGIN + ":99999/")
    restore.assert_not_called()
    assert pages.options[0]["start_url"] == ORIGIN + ":99999/"
    assert pages.options[0]["sign_ins"] == []


def _restore_with(state: object | None, *, error: BaseException | None = None):
    calls: list[tuple[object, ...]] = []

    @asynccontextmanager
    async def restore(*args: object):
        calls.append(args)
        if error is not None:
            raise error
        yield state

    return restore, calls


async def test_a_protected_restore_opens_one_protected_non_resumable_tab(monkeypatch) -> None:
    state = SimpleNamespace(name="protected-sign-in")
    restore, calls = _restore_with(state)
    monkeypatch.setattr(browser, "protected_restore", restore)
    pages = _Pages(_cdp_page(protected=True))
    toolset = _build(pages, credentials=True)
    async with toolset:
        await _open(toolset, _signed_in_deps(), ORIGIN + "/account")
        assert toolset.session is not None and toolset.session.resumable is False
    assert calls[0][-1] == ORIGIN
    assert len(pages.options) == 1
    assert pages.options[0]["protected_sign_in"] is state
    assert pages.options[0]["start_url"] == ORIGIN
    assert pages.options[0]["sign_ins"] == []


async def test_a_restore_that_opens_an_unprotected_tab_closes_it_and_refuses(monkeypatch) -> None:
    restore, _ = _restore_with(SimpleNamespace())
    monkeypatch.setattr(browser, "protected_restore", restore)
    pages = _Pages(_cdp_page(protected=False))
    toolset = _build(pages, credentials=True)
    async with toolset:
        assert await _open(toolset, _signed_in_deps(), ORIGIN) == UNAVAILABLE
        assert toolset.session is None
    assert pages.closed == 1
    assert len(pages.options) == 1


async def test_a_failing_restore_is_refused_without_leaking_its_error(monkeypatch) -> None:
    restore, _ = _restore_with(None, error=RuntimeError("cookie value hunter2"))
    monkeypatch.setattr(browser, "protected_restore", restore)
    pages = _Pages(_cdp_page(protected=False))
    toolset = _build(pages, credentials=True)
    async with toolset:
        result = await _open(toolset, _signed_in_deps(), ORIGIN)
    assert result == UNAVAILABLE
    assert "hunter2" not in result
    assert pages.options == []


async def test_a_cancelled_restore_is_not_turned_into_a_refusal(monkeypatch) -> None:
    restore, _ = _restore_with(None, error=asyncio.CancelledError())
    monkeypatch.setattr(browser, "protected_restore", restore)
    toolset = _build(_Pages(_cdp_page(protected=False)), credentials=True)
    with pytest.raises(asyncio.CancelledError):
        async with toolset:
            await _open(toolset, _signed_in_deps(), ORIGIN)
