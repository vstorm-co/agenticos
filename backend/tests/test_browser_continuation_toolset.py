"""The real continuation callback owns its protected tab through commit and teardown.

Only native I/O, persistence and controller-task creation are substituted. The
controller effect, toolset callback, view publication and tab lifecycle run together.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.browser_use import _toolset as browser
from app.agents.capabilities.browser_use._page import CdpPage, PagePolicy
from app.agents.deps import AgentDeps
from app.services import live_browse
from tests.test_browser_continuation_controller import ContinuationHarness
from tests.test_browser_credential_native import ORIGIN
from tests.test_browser_session import PRIVATE
from tests.test_browser_use import DONE_ARGS, _browsing_model, _policy

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def wire(monkeypatch):
    effect = ContinuationHarness(monkeypatch)
    pages, closed, controllers, options = [], [], [], []
    chat = AsyncMock(return_value=True)
    monkeypatch.setattr(live_browse, "available", lambda: True)
    monkeypatch.setattr(live_browse, "open_view", AsyncMock())
    monkeypatch.setattr(live_browse, "has_viewers", AsyncMock(return_value=False))
    monkeypatch.setattr(live_browse, "publish", AsyncMock())
    monkeypatch.setattr(live_browse, "protect_view", AsyncMock())
    monkeypatch.setattr(live_browse, "credential_redis", lambda: effect.writer.redis)

    @asynccontextmanager
    async def no_saved_state(*args):
        yield None

    monkeypatch.setattr(browser, "protected_restore", no_saved_state)

    @asynccontextmanager
    async def open_page(**kwargs):
        options.append(kwargs)
        page = CdpPage(MagicMock(), str(uuid4()), PagePolicy(None, 60, 1024))
        page.protect_credentials(ORIGIN)
        page.snapshot = AsyncMock(side_effect=page.output_guard.snapshot)
        page.location = AsyncMock(side_effect=page.output_guard.location)
        pages.append(page)
        if len(pages) == 1:
            page.continuation = effect.native
            page.credentials = effect.base.native
            effect.writer.page = page
        else:
            assert effect.in_transaction and effect.order[-1] == "export"
            assert kwargs["protected_sign_in"].provenance == effect.claim.provenance
            effect.order.append("open_owned")
        try:
            yield page
        finally:
            closed.append(page)
            if page is not pages[0]:
                effect.order.append("close_owned")

    async def create_controller(**kwargs):
        instance = SimpleNamespace(alive=True, close=AsyncMock(), **kwargs)
        controllers.append(instance)
        if len(controllers) == 1:
            effect.writer.continue_session = kwargs["continue_session"]
        return instance

    monkeypatch.setattr(browser.BrowserCredentialController, "create", create_controller)
    identity = effect.base.identity
    ctx = RunContext(
        deps=AgentDeps(
            run_id=identity.run_id,
            organization_id=identity.organization_id,
            agent_id=identity.agent_id,
            user_id=str(identity.user_id),
            browser_events=chat,
        ),
        model=_browsing_model(DONE_ARGS),
        usage=RunUsage(),
        tool_call_id="source-call",
    )
    toolset = browser.build_toolset(
        cdp_url="http://browser:9222",
        page_policy=PagePolicy(None, 60, 1024),
        loop_policy=_policy(),
        page_factory=open_page,
        credential_ids=identity.credential_ids,
    )

    async def invoke(name, args):
        tools = await toolset.get_tools(ctx)
        return await toolset.call_tool(name, args, ctx, tools[name])

    return SimpleNamespace(
        effect=effect,
        toolset=toolset,
        invoke=invoke,
        pages=pages,
        closed=closed,
        controllers=controllers,
        options=options,
        chat=chat,
    )


@pytest.mark.parametrize("outcome", ["success", "failed_commit", "cancelled_commit"])
async def test_real_callback_retains_or_unwinds_only_its_new_protected_tab(monkeypatch, outcome):
    h = wire(monkeypatch)
    effect, toolset = h.effect, h.toolset
    claim = effect.claim
    async with toolset:
        await h.invoke("browser_open", {"url": ORIGIN})
        original_session, original_view = toolset.session, toolset.view
        assert original_session.page is h.pages[0] and original_view is not None
        effect.writer._continuation_prepared = effect.plan_id
        if outcome == "success":
            await effect.writer._step_continuation(effect.plan())
        else:
            effect.failure = "commit"
            effect.cancel = outcome == "cancelled_commit"
            with pytest.raises(asyncio.CancelledError if effect.cancel else RuntimeError):
                await effect.writer._step_continuation(effect.plan())

        assert toolset.session is original_session and toolset.view is original_view
        assert h.pages[0].output_guard.active and h.pages[0] not in h.closed
        assert len(h.pages) == 2 and h.options[1]["sign_ins"] == []
        assert h.options[1]["start_url"] == ORIGIN
        effect.native.export.assert_awaited_once()
        effect.service.finish.assert_awaited_once()
        if outcome == "success":
            assert h.closed == [] and effect.order[-2:] == ["commit", "close_handle"]
            derived, _ = toolset.parked[claim.tab_id]
            view, controller = toolset.protected_views[claim.tab_id]
            assert derived.page is h.pages[1] and not derived.resumable
            assert view.call_id == claim.call_id != original_view.call_id
            assert not view.preview and view.remember is None
            assert controller is h.controllers[1]
            await view.emit(
                BrowserEvent(
                    kind="browser_frame",
                    call_id=claim.call_id,
                    step=1,
                    url=ORIGIN + "/" + PRIVATE,
                    title=PRIVATE,
                    image=PRIVATE,
                )
            )
            report = await h.invoke("browser_switch_tab", {"tab_id": claim.tab_id})
            assert PRIVATE not in report and toolset.session is derived
            assert toolset.view is view and toolset.credential_controller is controller
            assert claim.tab_id not in toolset.protected_views
            await h.invoke("browser_close_tab", {"tab_id": claim.tab_id})
            assert h.closed == [h.pages[1]] and toolset.session is original_session
            assert set(toolset.sessions()) == {"main"}
        else:
            assert h.closed == [h.pages[1]]
            assert toolset.parked == {} and toolset.protected_views == {}
            assert effect.order[-2:] == ["rollback", "close_owned"]
            assert set(toolset.sessions()) == {"main"}
            assert h.controllers[0].close.await_count == 0
        for call in h.chat.await_args_list + live_browse.publish.await_args_list:
            event = call.args[-1]
            assert event.output_protected and event.image is None
            assert PRIVATE not in event.model_dump_json()
    assert h.closed == [h.pages[1], h.pages[0]]
    assert toolset.sessions() == {} and toolset.protected_views == {}
