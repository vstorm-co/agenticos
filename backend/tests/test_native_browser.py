"""Native page contracts: exclusive leases, device failures and local takeover."""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from app.agents.browser_events import BrowserCommand
from app.agents.capabilities.browser_use import _local, _native
from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._native import NativePage
from app.agents.capabilities.browser_use._page import DomainRefused, PagePolicy
from app.services import device_hub
from tests.test_browser_use import _Control

pytestmark = pytest.mark.anyio
POLICY = PagePolicy(allowed_domains=["example.test"], candidate_cap=60, preview_width=1000)


def native_page() -> NativePage:
    return NativePage(
        _local._Commands(uuid4(), "native-browser-test", "lease"),
        "native-browser-test",
        POLICY,
        session_id=uuid4(),
        lease="lease",
    )


async def test_native_renderer_does_not_encode_or_export_a_picture() -> None:
    page = native_page()
    deliver = AsyncMock()
    async with page.stream(deliver):
        assert page.streaming
        assert await page.screenshot() is None
        await page.resize(800, 600, 2)
        assert page._scale == 1
    assert not page.streaming
    assert await page.capture_sign_in() is None
    deliver.assert_not_awaited()
    control = page.control(None, "person")
    assert control.browse_id == "native-browser-test"
    assert control.lease == "lease"


@pytest.mark.parametrize("direction", [-1, 1])
async def test_native_history_uses_its_own_engine_and_rechecks_location(
    monkeypatch: pytest.MonkeyPatch,
    direction: int,
) -> None:
    page = native_page()
    command = AsyncMock(return_value={})
    monkeypatch.setattr(page._native_commands, "_send", command)
    settle, location = AsyncMock(), AsyncMock()
    monkeypatch.setattr(page, "settle", settle)
    monkeypatch.setattr(page, "location", location)
    await (page.back() if direction == -1 else page.forward())
    command.assert_awaited_once_with("Native.history", {"offset": direction})
    settle.assert_awaited_once()
    location.assert_awaited_once()


async def test_trusted_native_input_yields_takeover_and_handback_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(side_effect=[{"held": True}, {"held": True}, {"held": False}])
    monkeypatch.setattr(device_hub, "call", call)
    control = native_page().control(None, "person")
    take = await control.poll()
    assert take is not None and take.type == "take_over" and take.by_user_id == "person"
    assert await control.poll() is None
    give = await control.wait(1)
    assert give is not None and give.type == "give_back"
    call.side_effect = None
    call.return_value = {"held": False}
    assert await control.wait(0) is None


@pytest.mark.parametrize("kind", ["take_over", "give_back", "type"])
async def test_remote_controls_share_native_hold_state(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    command = BrowserCommand.model_validate({"type": kind, "by_user_id": "person", "text": "text"})
    remote = _Control()
    remote._polled.append(command)
    call = AsyncMock(return_value={"held": kind == "take_over"})
    monkeypatch.setattr(device_hub, "call", call)
    control = native_page().control(remote, "person")
    assert await control.poll() == command
    if kind == "type":
        call.assert_not_awaited()
    else:
        assert call.call_args.args[2]["held"] == (kind == "take_over")


@pytest.mark.parametrize("reply", [None, [], {}, {"held": "yes"}])
async def test_native_control_rejects_invalid_device_replies(
    monkeypatch: pytest.MonkeyPatch,
    reply: object,
) -> None:
    monkeypatch.setattr(device_hub, "call", AsyncMock(return_value=reply))
    with pytest.raises(EndpointError, match="invalid control"):
        await native_page().control(None, "person").poll()


@pytest.mark.parametrize(
    "failure",
    [device_hub.DeviceUnavailable, device_hub.DeviceCallFailed, device_hub.DeviceCallTimedOut],
)
async def test_native_control_translates_expected_device_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: type[device_hub.DeviceUnavailable]
    | type[device_hub.DeviceCallFailed]
    | type[device_hub.DeviceCallTimedOut],
) -> None:
    monkeypatch.setattr(
        device_hub, "call", AsyncMock(side_effect=failure(message="Device unavailable"))
    )
    with pytest.raises(EndpointError, match="Device unavailable"):
        await native_page().control(None, "person").poll()


async def test_a_native_control_wait_checks_again_after_an_empty_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        device_hub, "call", AsyncMock(side_effect=[{"held": False}, {"held": True}])
    )
    command = await native_page().control(None, "person").wait(1)
    assert command is not None and command.type == "take_over"


@pytest.mark.parametrize("close", [False, True])
@pytest.mark.parametrize("resume", [False, True])
async def test_native_factory_releases_its_lease_without_destroying_the_conversation_tab(
    monkeypatch: pytest.MonkeyPatch,
    resume: bool,
    close: bool,
) -> None:
    session = uuid4()
    call = AsyncMock(
        return_value={
            "id": "native-browser-test",
            "lease": "lease",
            "native": True,
            "reused": resume,
        }
    )
    navigate = AsyncMock()
    monkeypatch.setattr(device_hub, "call", call)
    monkeypatch.setattr(NativePage, "navigate", navigate)
    async with _local.page_factory(session)(
        cdp_url="",
        start_url=None if resume else "https://example.test/",
        policy=POLICY,
        conversation_scope="a" * 64,
    ) as page:
        assert isinstance(page, NativePage)
        assert call.call_args.args[2]["scope"] == "a" * 64
        assert call.call_args.args[2]["resume"] is resume
        page.close_on_release = close
    assert call.call_args.args == (
        session,
        "browser.release",
        {"id": "native-browser-test", "lease": "lease", **({"close": True} if close else {})},
    )
    assert navigate.await_count == (0 if resume else 1)


@pytest.mark.parametrize("lease", [None, "", 123])
async def test_native_factory_requires_a_lease(
    monkeypatch: pytest.MonkeyPatch, lease: object
) -> None:
    monkeypatch.setattr(
        device_hub,
        "call",
        AsyncMock(return_value={"id": "native-browser-test", "native": True, "lease": lease}),
    )
    with pytest.raises(EndpointError, match="lease"):
        async with _local.page_factory(uuid4())(
            cdp_url="", start_url="https://example.test/", policy=POLICY
        ):
            pytest.fail("An unleased tab must not be used")


async def test_native_commands_include_the_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value={})
    monkeypatch.setattr(device_hub, "call", call)
    await _local._Commands(uuid4(), "native-browser-test", "lease")._send(
        "Runtime.evaluate", {"expression": "1"}
    )
    assert call.call_args.args[2]["lease"] == "lease"


@pytest.mark.parametrize("native", [False, True])
async def test_persistent_resume_does_not_silently_open_an_old_chromium_desktop(
    monkeypatch: pytest.MonkeyPatch,
    native: bool,
) -> None:
    monkeypatch.setattr(device_hub, "call", AsyncMock(return_value={"id": "old-browser"}))
    monkeypatch.setattr(_local._Commands, "_send", AsyncMock(return_value={}))
    monkeypatch.setattr(_local.LocalPage, "resize", AsyncMock())
    with pytest.raises(EndpointError, match=r"start URL|does not support persistent"):
        async with _local.page_factory(uuid4(), native=native)(
            cdp_url="", start_url=None, policy=POLICY
        ):
            pytest.fail("An old desktop cannot resume native conversations")


async def test_native_factory_refuses_chromium_emulation_and_releases_the_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.capabilities.browser_use._route import BrowserRoute

    call = AsyncMock(return_value={"id": "native-browser-test", "lease": "lease", "native": True})
    monkeypatch.setattr(device_hub, "call", call)
    with pytest.raises(DomainRefused, match="language and time zone"):
        async with _local.page_factory(uuid4())(
            cdp_url="",
            start_url="https://example.test/",
            policy=POLICY,
            route=BrowserRoute(timezone="UTC"),
        ):
            pytest.fail("Native WebViews do not emulate Chromium settings")
    assert call.call_args.args[1] == "browser.release"


@pytest.mark.parametrize("failure", [False, True])
async def test_dom_actions_are_marked_without_leaking_into_read_operations(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    page = native_page()
    call = AsyncMock(return_value={"result": {"value": None}})
    monkeypatch.setattr(device_hub, "call", call)
    if failure:
        call.side_effect = device_hub.DeviceCallFailed(message="Page action refused")
        with pytest.raises(EndpointError, match="refused"):
            await page.scroll("down")
    else:
        await page.scroll("down")
    assert call.call_args.args[2]["native_action"] is True
    assert not _native.native_action_active()


@pytest.mark.parametrize("identity", ["complete", "missing"])
async def test_local_read_resumes_a_conversation_under_its_complete_identity(identity: str) -> None:
    from app.agents.capabilities.browser_use._loop import LoopPolicy
    from app.agents.capabilities.browser_use._toolset import build_toolset
    from app.agents.deps import AgentDeps
    from tests.test_browser_use import DONE_ARGS, _browsing_model, _Opener, _tool_context

    opener = _Opener()
    toolset = build_toolset(
        cdp_url="",
        page_policy=POLICY,
        loop_policy=LoopPolicy(max_steps=3, preview=False),
        page_factory=opener,
        resume_local=True,
    )
    ctx = _tool_context(_browsing_model(DONE_ARGS))
    ctx.deps = (
        AgentDeps(
            organization_id=uuid4(), user_id="person", agent_id=uuid4(), conversation_id=uuid4()
        )
        if identity == "complete"
        else AgentDeps()
    )
    async with toolset:
        tools = await toolset.get_tools(ctx)
        result = await toolset.call_tool("browser_read", {}, ctx, tools["browser_read"])
        if identity == "complete":
            assert opener.opened[0]["start_url"] is None
            assert len(opener.opened[0]["conversation_scope"]) == 64
            assert "PAGE:" in str(result)
        else:
            assert "No page is open" in str(result)
            assert not opener.opened


async def test_a_failed_native_resume_is_a_visible_refusal() -> None:
    from app.agents.capabilities.browser_use._loop import LoopPolicy
    from app.agents.capabilities.browser_use._toolset import build_toolset
    from app.agents.deps import AgentDeps
    from tests.test_browser_use import DONE_ARGS, _browsing_model, _Opener, _tool_context

    opener = _Opener(fails=EndpointError("The native tab was closed"))
    toolset = build_toolset(
        cdp_url="",
        page_policy=POLICY,
        loop_policy=LoopPolicy(max_steps=3, preview=False),
        page_factory=opener,
        resume_local=True,
    )
    ctx = _tool_context(_browsing_model(DONE_ARGS))
    ctx.deps = AgentDeps(
        organization_id=uuid4(), user_id="person", agent_id=uuid4(), conversation_id=uuid4()
    )
    async with toolset:
        tools = await toolset.get_tools(ctx)
        result = await toolset.call_tool("browser_read", {}, ctx, tools["browser_read"])
    assert result == "The native tab was closed"


async def test_explicit_chromium_local_browsing_keeps_its_original_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = AsyncMock(return_value={"id": "chromium"})
    monkeypatch.setattr(device_hub, "call", call)
    monkeypatch.setattr(_local._Commands, "_send", AsyncMock(return_value={}))
    monkeypatch.setattr(_local.LocalPage, "resize", AsyncMock())
    monkeypatch.setattr(_local.LocalPage, "navigate", AsyncMock())
    async with _local.page_factory(uuid4(), native=False)(
        cdp_url="", start_url="https://example.test/", policy=POLICY
    ):
        assert call.call_args.args[2] == {}
    assert call.call_args.args[1] == "browser.close"


async def test_a_local_open_without_conversation_identity_cannot_reuse_another_tab() -> None:
    from app.agents.capabilities.browser_use._loop import LoopPolicy
    from app.agents.capabilities.browser_use._toolset import build_toolset
    from tests.test_browser_use import DONE_ARGS, _browsing_model, _Opener, _tool_context

    opener = _Opener()
    toolset = build_toolset(
        cdp_url="",
        page_policy=POLICY,
        loop_policy=LoopPolicy(max_steps=3, preview=False),
        page_factory=opener,
        resume_local=True,
    )
    ctx = _tool_context(_browsing_model(DONE_ARGS))
    async with toolset:
        tools = await toolset.get_tools(ctx)
        await toolset.call_tool(
            "browser_open", {"url": "https://example.test/"}, ctx, tools["browser_open"]
        )
    assert "conversation_scope" not in opener.opened[0]


@pytest.mark.parametrize(
    ("config", "native"),
    [
        ({}, True),
        ({"prefer_native_browser": False}, False),
        ({"vision": True}, False),
        ({"timezone": "UTC"}, False),
        ({"locale": "pl-PL"}, False),
    ],
)
async def test_local_engine_selection_keeps_a_chromium_compatibility_option(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, object],
    native: bool,
) -> None:

    from app.agents.capabilities import browser_use
    from app.agents.capabilities.browser_use._capability import WebBrowser
    from app.agents.capabilities.browser_use._toolset import PageFactory
    from tests.test_browser_use import _build_capability

    seen: list[bool] = []

    def factory(session_id: UUID, *, native: bool = True) -> PageFactory:
        seen.append(native)
        return _local.page_factory(session_id, native=native)

    monkeypatch.setattr(browser_use, "local_page_factory", factory)
    capability = _build_capability(config, {"local_browser_session": uuid4()})
    assert isinstance(capability, WebBrowser)
    assert seen == [native]
    assert capability.resume_local is native


@pytest.mark.parametrize("native", [False, True])
async def test_only_native_local_runs_are_told_how_to_resume_conversation_tabs(
    native: bool,
) -> None:
    from app.agents.capabilities.browser_use._capability import WebBrowser

    instructions = WebBrowser(resume_local=native).get_instructions()
    assert ("call browser_read first" in instructions) is native
    assert "untrusted data" in instructions


@pytest.mark.parametrize("failure", [False, True])
async def test_a_native_lease_is_renewed_even_without_a_preview(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    import anyio

    renewed = anyio.Event()
    calls: list[str] = []

    async def call(
        session_id: UUID, op: str, args: dict[str, JsonValue], *, timeout: float
    ) -> dict[str, JsonValue]:
        calls.append(op)
        if op == "browser.open":
            return {"id": "native-browser-test", "lease": "lease", "native": True}
        if op == "browser.heartbeat":
            renewed.set()
            if failure:
                raise device_hub.DeviceCallFailed(message="Native lease expired")
        return {}

    monkeypatch.setattr(device_hub, "call", call)
    monkeypatch.setattr(_local, "LEASE_HEARTBEAT", 0.01)
    monkeypatch.setattr(NativePage, "navigate", AsyncMock())
    async with _local.page_factory(uuid4())(
        cdp_url="", start_url="https://example.test/", policy=POLICY
    ) as page:
        assert isinstance(page, NativePage)
        with anyio.fail_after(1):
            await renewed.wait()
        if failure:
            with pytest.raises(EndpointError, match="Native lease expired"):
                await page._native_commands._send("Runtime.evaluate", {"expression": "1"})
    assert calls[-1] == "browser.release"
    total = len(calls)
    await anyio.sleep(0.03)
    assert len(calls) == total


async def test_a_heartbeat_bug_still_releases_the_native_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anyio

    failed = anyio.Event()
    calls: list[str] = []

    async def call(
        session_id: UUID, op: str, args: dict[str, JsonValue], *, timeout: float
    ) -> dict[str, JsonValue]:
        calls.append(op)
        if op == "browser.open":
            return {"id": "native-browser-test", "lease": "lease", "native": True}
        if op == "browser.heartbeat":
            failed.set()
            raise ValueError("heartbeat bug")
        return {}

    monkeypatch.setattr(device_hub, "call", call)
    monkeypatch.setattr(_local, "LEASE_HEARTBEAT", 0.01)
    monkeypatch.setattr(NativePage, "navigate", AsyncMock())
    with pytest.raises(ValueError, match="heartbeat bug"):
        async with _local.page_factory(uuid4())(
            cdp_url="", start_url="https://example.test/", policy=POLICY
        ):
            with anyio.fail_after(1):
                await failed.wait()
    assert calls[-1] == "browser.release"


async def test_a_heartbeat_cleanup_bug_preserves_the_primary_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import anyio

    failed = anyio.Event()

    async def call(
        session_id: UUID, op: str, args: dict[str, JsonValue], *, timeout: float
    ) -> dict[str, JsonValue]:
        if op == "browser.open":
            return {"id": "native-browser-test", "lease": "lease", "native": True}
        if op == "browser.heartbeat":
            failed.set()
            raise ValueError("heartbeat cleanup bug")
        return {}

    monkeypatch.setattr(device_hub, "call", call)
    monkeypatch.setattr(_local, "LEASE_HEARTBEAT", 0.01)
    monkeypatch.setattr(NativePage, "navigate", AsyncMock())
    with pytest.raises(DomainRefused, match="primary failure"):
        async with _local.page_factory(uuid4())(
            cdp_url="", start_url="https://example.test/", policy=POLICY
        ):
            with anyio.fail_after(1):
                await failed.wait()
            raise DomainRefused("primary failure")
    assert "heartbeat cleanup bug" in caplog.text


async def test_explicit_close_destroys_a_native_tab_and_other_tabs_have_distinct_scopes(
    monkeypatch,
):
    from app.agents.capabilities.browser_use._loop import BrowseSession, LoopPolicy
    from app.agents.capabilities.browser_use._toolset import build_toolset
    from app.agents.deps import AgentDeps
    from tests.test_browser_use import DONE_ARGS, _browsing_model, _Opener, _tool_context

    opener = _Opener()
    ts = build_toolset(
        cdp_url="",
        page_policy=POLICY,
        loop_policy=LoopPolicy(max_steps=3, preview=False),
        page_factory=opener,
        resume_local=True,
    )
    ctx = _tool_context(_browsing_model(DONE_ARGS))
    ctx.deps = AgentDeps(
        organization_id=uuid4(), user_id="person", agent_id=uuid4(), conversation_id=uuid4()
    )
    async with ts:
        tools = await ts.get_tools(ctx)
        await ts.call_tool("browser_read", {}, ctx, tools["browser_read"])
        await ts.call_tool(
            "browser_new_tab", {"url": "https://example.test/"}, ctx, tools["browser_new_tab"]
        )
        assert opener.opened[0]["conversation_scope"] != opener.opened[1]["conversation_scope"]
        page = native_page()
        monkeypatch.setattr(
            page, "location", AsyncMock(return_value=("https://example.test/", "Example"))
        )
        ts.session = BrowseSession(page=page)
        await ts.call_tool(
            "browser_close_tab", {"tab_id": ts.tab_id}, ctx, tools["browser_close_tab"]
        )
        assert page.close_on_release
