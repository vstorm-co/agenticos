"""Local browsing uses the paired session and closes its disposable window."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use import _local as module
from app.agents.capabilities.browser_use._page import DomainRefused, PagePolicy

pytestmark = pytest.mark.anyio


async def test_local_browser_closes_after_navigation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = uuid4()
    call = AsyncMock(side_effect=[{"id": "window"}, {}])
    monkeypatch.setattr(module.device_hub, "call", call)
    monkeypatch.setattr(module.LocalPage, "resize", AsyncMock())
    monkeypatch.setattr(module.LocalPage, "navigate", AsyncMock(side_effect=RuntimeError("gone")))
    with pytest.raises(RuntimeError, match="gone"):
        async with module.page_factory(session)(
            cdp_url="",
            start_url="https://example.com",
            policy=PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200),
        ):
            pytest.fail("Navigation failed before yielding")
    assert call.call_args.args == (session, "browser.close", {"id": "window"})


async def test_local_browser_refuses_domains_before_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock()
    monkeypatch.setattr(module.device_hub, "call", call)
    with pytest.raises(DomainRefused):
        async with module.page_factory(uuid4())(
            cdp_url="",
            start_url="https://denied.example",
            policy=PagePolicy(
                allowed_domains=["example.com"], candidate_cap=100, preview_width=1200
            ),
        ):
            pytest.fail("Refused domain")
    call.assert_not_called()


async def test_local_commands_never_send_a_debugging_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = uuid4()
    call = AsyncMock(return_value={"result": {"value": "title"}})
    monkeypatch.setattr(module.device_hub, "call", call)
    commands = module._Commands(session, "owned-window")
    for method, native in [
        (commands.evaluate, "Runtime.evaluate"),
        (commands.navigate, "Page.navigate"),
        (commands.captureScreenshot, "Page.captureScreenshot"),
        (commands.dispatchMouseEvent, "Input.dispatchMouseEvent"),
        (commands.dispatchKeyEvent, "Input.dispatchKeyEvent"),
        (commands.insertText, "Input.insertText"),
        (commands.setDeviceMetricsOverride, "Emulation.setDeviceMetricsOverride"),
    ]:
        await method(params={}, session_id="ignored")
        assert call.call_args.args == (
            session,
            "browser.command",
            {"id": "owned-window", "method": native, "params": {}},
        )
    assert (
        await module.LocalPage(
            commands,
            "owned-window",
            PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200),
        ).capture_sign_in()
        is None
    )
