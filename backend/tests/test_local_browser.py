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
    call = AsyncMock(side_effect=[{"id": "window"}, {}, {}])
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


async def test_local_stream_delivers_frames_and_cancels_its_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anyio

    ready = anyio.Event()
    screenshot = AsyncMock(side_effect=[None, "jpeg"])
    monkeypatch.setattr(module.LocalPage, "screenshot", screenshot)
    frames: list[str] = []

    async def deliver(frame: str) -> None:
        frames.append(frame)
        ready.set()

    page = module.LocalPage(
        module._Commands(uuid4(), "window"),
        "window",
        PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200),
    )
    async with page.stream(deliver):
        with anyio.fail_after(3):
            await ready.wait()
    assert frames == ["jpeg"]


async def test_cleanup_failure_does_not_mask_the_browse_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    call = AsyncMock(
        side_effect=[{"id": "window"}, {}, module.device_hub.DeviceUnavailable(message="offline")]
    )
    monkeypatch.setattr(module.device_hub, "call", call)
    monkeypatch.setattr(module.LocalPage, "resize", AsyncMock())
    monkeypatch.setattr(module.LocalPage, "navigate", AsyncMock())
    async with module.page_factory(uuid4())(
        cdp_url="",
        start_url="https://example.com",
        policy=PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200),
    ) as page:
        assert isinstance(page, module.LocalPage)
    assert "Could not release a local browser" in caplog.text
    call.side_effect = None
    call.return_value = {"id": None}
    with pytest.raises(RuntimeError, match="did not open"):
        async with module.page_factory(uuid4())(
            cdp_url="",
            start_url="https://example.com",
            policy=PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200),
        ):
            pytest.fail("Invalid native answer")


async def test_local_browsing_applies_locale_and_refuses_incompatible_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.capabilities.browser_use._route import BrowserRoute

    call = AsyncMock(
        side_effect=[{"id": "window"}, {}, {"result": {"value": "Chrome"}}, {}, {}, {}, {}]
    )
    monkeypatch.setattr(module.device_hub, "call", call)
    monkeypatch.setattr(module.LocalPage, "resize", AsyncMock())
    monkeypatch.setattr(module.LocalPage, "navigate", AsyncMock())
    factory = module.page_factory(uuid4())
    policy = PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200)
    async with factory(
        cdp_url="",
        start_url="https://example.com",
        policy=policy,
        route=BrowserRoute(timezone="Europe/Warsaw", locale="pl-PL"),
    ):
        pass
    assert [
        entry.args[2]["method"]
        for entry in call.await_args_list
        if entry.args[1] == "browser.command"
    ] == [
        "Emulation.setTimezoneOverride",
        "Runtime.evaluate",
        "Emulation.setUserAgentOverride",
        "Emulation.setLocaleOverride",
        "Page.addScriptToEvaluateOnNewDocument",
    ]
    call.reset_mock()
    with pytest.raises(DomainRefused, match="without a proxy"):
        async with factory(
            cdp_url="",
            start_url="https://example.com",
            policy=policy,
            route=BrowserRoute(proxy_server="http://proxy:8080"),
        ):
            pytest.fail("Incompatible route")
    call.assert_not_called()
    call.side_effect = [{"id": "window"}, {"result": {"value": None}}, {}]
    with pytest.raises(RuntimeError, match="user agent"):
        async with factory(
            cdp_url="",
            start_url="https://example.com",
            policy=policy,
            route=BrowserRoute(locale="pl-PL"),
        ):
            pytest.fail("Invalid native user agent")


@pytest.mark.parametrize(
    "failure",
    [
        module.device_hub.DeviceCallFailed,
        module.device_hub.DeviceUnavailable,
        module.device_hub.DeviceCallTimedOut,
    ],
)
async def test_native_failures_follow_the_shared_browser_failure_contract(
    monkeypatch: pytest.MonkeyPatch,
    failure: type[
        module.device_hub.DeviceCallFailed
        | module.device_hub.DeviceUnavailable
        | module.device_hub.DeviceCallTimedOut
    ],
) -> None:
    from app.agents.capabilities.browser_use._endpoint import EndpointError

    monkeypatch.setattr(
        module.device_hub,
        "call",
        AsyncMock(side_effect=failure(message="Execution context was destroyed")),
    )
    with pytest.raises(EndpointError, match="Execution context was destroyed"):
        await module._Commands(uuid4(), "window").evaluate(params={}, session_id="window")


async def test_native_history_and_reload_use_the_owned_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value={})
    monkeypatch.setattr(module.device_hub, "call", call)
    session = uuid4()
    commands = module._Commands(session, "owned-window")
    await commands.getNavigationHistory(session_id="ignored")
    await commands.navigateToHistoryEntry(params={"entryId": 1}, session_id="ignored")
    await commands.reload(session_id="ignored")
    assert [entry.args[2] for entry in call.await_args_list] == [
        {"id": "owned-window", "method": "Page.getNavigationHistory", "params": {}},
        {"id": "owned-window", "method": "Page.navigateToHistoryEntry", "params": {"entryId": 1}},
        {"id": "owned-window", "method": "Page.reload", "params": {}},
    ]


async def test_failed_background_capture_does_not_mask_tab_cleanup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import anyio

    from app.agents.capabilities.browser_use._endpoint import EndpointError

    failed = anyio.Event()

    async def screenshot() -> str | None:
        failed.set()
        raise EndpointError("Device offline")

    page = module.LocalPage(
        module._Commands(uuid4(), "window"),
        "window",
        PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200),
    )
    monkeypatch.setattr(page, "screenshot", screenshot)

    async def deliver(image: str) -> None:
        pytest.fail("No frame should arrive")

    async with page.stream(deliver):
        await failed.wait()
        assert not page.streaming
    assert "Local browser preview stopped" in caplog.text


async def test_context_replacement_is_retried_through_the_local_error_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(
        side_effect=[
            module.device_hub.DeviceCallFailed(message="Execution context was destroyed"),
            {"result": {"type": "string", "value": "new-document"}},
        ]
    )
    monkeypatch.setattr(module.device_hub, "call", call)
    monkeypatch.setattr("app.agents.capabilities.browser_use._page.asyncio.sleep", AsyncMock())
    page = module.LocalPage(
        module._Commands(uuid4(), "owned-window"),
        "owned-window",
        PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1200),
    )
    assert await page._document() == "new-document"
    assert call.await_count == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"model_service": "model", "browser": True},
        {"mcp_services": ["files"], "browser": True},
    ],
)
def test_browser_only_target_cannot_grant_local_files_or_services(payload):
    from pydantic import ValidationError

    from app.schemas.local_target import LocalTarget

    with pytest.raises(ValidationError):
        LocalTarget.model_validate(payload)


def test_browser_only_target_is_independent_of_folder_grants():
    from app.schemas.local_target import LocalTarget

    target = LocalTarget(browser=True)
    assert target.folder is None and target.model_service is None and not target.mcp_services


def test_browser_only_selection_never_creates_a_filesystem_workspace() -> None:
    from pydantic_ai.workspaces import WorkspaceUnavailableError

    from app.schemas.local_target import LocalTarget
    from app.services.device_hub.workspace import DeviceWorkspace

    with pytest.raises(WorkspaceUnavailableError, match="approved folder"):
        DeviceWorkspace(uuid4(), uuid4(), LocalTarget(browser=True))
