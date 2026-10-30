"""Readiness, manual input and session preview regressions at the CDP boundary."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import anyio
import pytest

from app.agents.browser_events import BrowserCommand
from app.agents.capabilities.browser_use import _loop
from app.agents.capabilities.browser_use._direct import DirectView
from app.agents.capabilities.browser_use._endpoint import EndpointError
from app.agents.capabilities.browser_use._loop import BrowseSession, held
from app.agents.capabilities.browser_use._page import (
    CdpPage,
    DomainRefused,
    PagePolicy,
    StaleElement,
)
from app.agents.capabilities.browser_use._toolset import BrowserToolset
from tests.test_browser_use import GIVE, TAKE, _Control, _FakePage, _Frames

pytestmark = pytest.mark.anyio


class _Cdp:
    def __init__(self) -> None:
        self.send = self
        self.Page = self
        self.navigate = AsyncMock(return_value={"loaderId": "new"})
        self.reload = AsyncMock(return_value={})
        self.getNavigationHistory = AsyncMock(return_value={"currentIndex": 0, "entries": []})
        self.navigateToHistoryEntry = AsyncMock(return_value={})


def page() -> tuple[CdpPage, _Cdp]:
    client = _Cdp()
    return CdpPage(
        client,
        "tab",
        PagePolicy(allowed_domains=["example.test"], candidate_cap=100, preview_width=1000),
    ), client


async def test_reopening_the_same_url_waits_for_a_new_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, client = page()
    evaluate = AsyncMock(side_effect=[{"value": "old"}, {"value": "new"}, {"value": True}])
    monkeypatch.setattr(target, "_evaluate", evaluate)
    await target.navigate("https://example.test/page")
    client.navigate.assert_awaited_once()
    assert evaluate.await_args_list[1].args == ("String(performance.timeOrigin)",)
    assert evaluate.await_args_list[-1].kwargs == {"await_promise": True}


async def test_same_document_navigation_has_no_document_change_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, client = page()
    client.navigate.return_value = {}
    evaluate = AsyncMock(side_effect=[{"value": "old"}, {"value": True}])
    monkeypatch.setattr(target, "_evaluate", evaluate)
    await target.navigate("https://example.test/page#section")
    assert evaluate.await_count == 2


async def test_failed_and_forbidden_navigations_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, client = page()
    monkeypatch.setattr(target, "_evaluate", AsyncMock(return_value={"value": "old"}))
    with pytest.raises(StaleElement):
        await target.navigate("https://other.test/")
    client.navigate.assert_not_awaited()
    client.navigate.return_value = {"errorText": "net::ERR_FAILED"}
    with pytest.raises(EndpointError, match="could not load"):
        await target.navigate("https://example.test/")


async def test_missing_or_unreplaced_documents_do_not_look_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, _ = page()
    evaluate = AsyncMock(return_value={})
    monkeypatch.setattr(target, "_evaluate", evaluate)
    with pytest.raises(EndpointError, match="identify"):
        await target._document()
    evaluate.return_value = {"value": "old"}
    monkeypatch.setattr("app.agents.capabilities.browser_use._page._READY_ATTEMPTS", 1)
    monkeypatch.setattr("app.agents.capabilities.browser_use._page.asyncio.sleep", AsyncMock())
    with pytest.raises(EndpointError, match="new document"):
        await target._ready_after("old")
    evaluate.return_value = {"value": False}
    with pytest.raises(EndpointError, match="still loading"):
        await target.settle()
    evaluate.return_value = {"value": True}
    await target.settle()


@pytest.mark.parametrize("offset", [-1, 1])
async def test_history_checks_the_destination(offset: int, monkeypatch: pytest.MonkeyPatch) -> None:
    target, client = page()
    await target._history(offset)
    client.navigateToHistoryEntry.assert_not_awaited()
    client.getNavigationHistory.return_value = {
        "currentIndex": 1,
        "entries": [{"id": 1, "url": "https://other.test/"}] * 3,
    }
    with pytest.raises(StaleElement, match="history entry"):
        await target._history(offset)
    client.getNavigationHistory.return_value["entries"] = [
        {"id": 1, "url": "https://example.test/"}
    ] * 3
    monkeypatch.setattr(
        target,
        "_evaluate",
        AsyncMock(
            side_effect=[
                {"value": "old"},
                {"value": "https://example.test/"},
                {"value": "new"},
                {"value": True},
            ]
        ),
    )
    await (target.back() if offset < 0 else target.forward())
    client.navigateToHistoryEntry.assert_awaited_once_with(params={"entryId": 1}, session_id="tab")


@pytest.mark.parametrize("same_url", [False, True])
async def test_history_handles_same_document_entries(
    same_url: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, client = page()
    client.getNavigationHistory.return_value = {
        "currentIndex": 1,
        "entries": [{"id": 1, "url": "https://example.test/"}] * 2,
    }
    old_url = "https://example.test/" if same_url else "https://example.test/other"
    monkeypatch.setattr(
        target,
        "_evaluate",
        AsyncMock(
            side_effect=[
                {"value": "old"},
                {"value": old_url},
                {"value": "old"},
                {"value": "https://example.test/"},
                {"value": True},
            ]
        ),
    )
    await target.back()


async def test_reload_checks_domain_and_new_document(monkeypatch: pytest.MonkeyPatch) -> None:
    target, client = page()
    evaluate = AsyncMock(return_value={"value": "https://other.test/"})
    monkeypatch.setattr(target, "_evaluate", evaluate)
    with pytest.raises(StaleElement):
        await target.reload()
    client.reload.assert_not_awaited()
    evaluate.side_effect = [
        {"value": "https://example.test/"},
        {"value": "old"},
        {"value": "new"},
        {"value": True},
    ]
    await target.reload()
    client.reload.assert_awaited_once_with(session_id="tab")


async def test_metadata_does_not_require_collecting_dom(monkeypatch: pytest.MonkeyPatch) -> None:
    target, _ = page()
    evaluate = AsyncMock(
        return_value={"value": {"url": "https://example.test/", "title": "Example"}}
    )
    monkeypatch.setattr(target, "_evaluate", evaluate)
    assert await target.location() == ("https://example.test/", "Example")
    evaluate.return_value = {"value": {"url": "https://other.test/", "title": "Other"}}
    with pytest.raises(DomainRefused):
        await target.location()
    evaluate.return_value = {"value": {"url": 3}}
    with pytest.raises(EndpointError):
        await target.location()


async def test_typing_is_not_blocked_by_slow_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _FakePage()
    started, typed = anyio.Event(), anyio.Event()

    async def screenshot() -> str | None:
        started.set()
        await typed.wait()
        return None

    async def insert(text: str) -> None:
        typed.set()

    monkeypatch.setattr(target, "screenshot", screenshot)
    monkeypatch.setattr(target, "insert_text", insert)

    class Control:
        sent = False

        async def wait(self, timeout: float) -> BrowserCommand:
            if self.sent:
                return GIVE
            self.sent = True
            await started.wait()
            return BrowserCommand(type="type", text="hello", by_user_id=TAKE.by_user_id)

    with anyio.fail_after(1):
        await held(
            BrowseSession(target),
            Control(),
            _Frames(),
            call_id="call",
            by="Ada",
            by_user_id=TAKE.by_user_id,
            remember=None,
        )
    assert typed.is_set()


async def test_manual_navigation_refusal_keeps_the_hold() -> None:
    target, frames = _FakePage(refuse="Outside allowed domains"), _Frames()
    await held(
        BrowseSession(target),
        _Control(BrowserCommand(type="navigate", url="https://other.test/"), GIVE),
        frames,
        call_id="call",
        by=None,
        by_user_id=None,
        remember=None,
    )
    assert frames.of("browser_control_error")[0].detail == "Outside allowed domains"
    assert len(frames.of("browser_released")) == 1


async def test_navigation_only_applies_while_held() -> None:
    target, frames = _FakePage(), _Frames()
    commands = [BrowserCommand(type=kind) for kind in ("back", "forward", "reload")]
    commands += [BrowserCommand(type="navigate", url="https://example.test/"), GIVE]
    await held(
        BrowseSession(target),
        _Control(*commands),
        frames,
        call_id="call",
        by=None,
        by_user_id=None,
        remember=None,
    )
    assert target.done == ["back", "forward", "reload", "navigate:https://example.test/"]
    await _loop.between_steps(target, _Control(polled=BrowserCommand(type="reload")))
    assert target.done.count("reload") == 1


async def test_direct_stream_outlives_tool_calls_and_closes_before_tab() -> None:
    target, toolset, frames = _FakePage(painted=("paint",)), BrowserToolset(), _Frames()
    view = DirectView("call", frames, None, None, None, True)

    @asynccontextmanager
    async def factory() -> AsyncGenerator[_FakePage]:
        try:
            yield target
        finally:
            target.done.append("tab:closed")

    await toolset.watch(view)
    await toolset.open(factory)
    await toolset.watch(view)
    await toolset.watch(view)
    assert target.streaming
    assert target.done.count("stream:on") == 1
    await toolset.close()
    assert target.done[-2:] == ["stream:off", "tab:closed"]
    assert not target.streaming


async def test_history_waits_for_navigation_and_reports_a_stalled_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, client = page()
    client.getNavigationHistory.return_value = {
        "currentIndex": 1,
        "entries": [{"id": 1, "url": "https://example.test/new"}] * 2,
    }
    evaluate = AsyncMock(
        side_effect=[
            {"value": "old"},
            {"value": "https://example.test/old"},
            {"value": "old"},
            {"value": "https://example.test/old"},
            {"value": "new"},
            {"value": True},
        ]
    )
    monkeypatch.setattr(target, "_evaluate", evaluate)
    sleep = AsyncMock()
    monkeypatch.setattr("app.agents.capabilities.browser_use._page.asyncio.sleep", sleep)
    await target.back()
    sleep.assert_awaited_once()
    monkeypatch.setattr("app.agents.capabilities.browser_use._page._READY_ATTEMPTS", 1)
    evaluate.side_effect = [
        {"value": "old"},
        {"value": "https://example.test/old"},
        {"value": "old"},
        {"value": "https://example.test/old"},
    ]
    with pytest.raises(EndpointError, match="history"):
        await target.back()


async def test_a_forbidden_location_is_reported_without_blocking_give_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, frames = _FakePage(), _Frames()
    checked = anyio.Event()

    async def location() -> tuple[str, str]:
        checked.set()
        raise DomainRefused("Outside allowed domains")

    monkeypatch.setattr(target, "location", location)

    class Control:
        async def wait(self, timeout: float) -> BrowserCommand:
            await checked.wait()
            return GIVE

    await held(
        BrowseSession(target),
        Control(),
        frames,
        call_id="call",
        by=None,
        by_user_id=None,
        remember=None,
    )
    assert len(frames.of("browser_released")) == 1


async def test_streaming_state_matches_the_native_preview_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.capabilities.browser_use._local import LocalPage

    target = LocalPage(
        object(), "tab", PagePolicy(allowed_domains=None, candidate_cap=100, preview_width=1000)
    )
    assert not target.streaming
    monkeypatch.setattr(target, "screenshot", AsyncMock(return_value=None))

    async def deliver(image: str) -> None:
        pytest.fail("No image was captured")

    async with target.stream(deliver):
        assert target.streaming
    assert not target.streaming


@pytest.mark.parametrize("connection", ["hosted", "local"])
async def test_non_builtin_endpoints_need_no_deployment_cdp_address(connection: str) -> None:
    from app.agents.capabilities.browser_use import (
        WebBrowserConfig,
        connection_problems,
        validate_cdp_url,
    )

    config = WebBrowserConfig.model_validate(
        {"connection": connection, "hosted_url": "wss://browser.example.test"}
    )
    validate_cdp_url(config)
    assert connection_problems(config, has_secret=True) == []


@pytest.mark.parametrize("resize", [False, True])
async def test_a_decision_is_discarded_if_a_person_changes_the_page_while_it_is_thinking(
    resize: bool,
) -> None:
    from tests.test_browser_use import CLICK0, DONE, _watched

    target, frames = _FakePage(), _Frames()
    control = _Control(GIVE)
    decided = False

    async def decide(*args: object) -> _loop.Step:
        nonlocal decided
        if not decided:
            decided = True
            control._polled.append(
                BrowserCommand(type="resize", width=800, height=600) if resize else TAKE
            )
            return CLICK0
        return DONE

    result, _ = await _watched(target, decide, control, frames, max_steps=3)
    assert result.outcome == "done"
    assert "click:0" not in target.done


async def test_a_held_stream_does_not_capture_extra_screenshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, frames = _FakePage(), _Frames()
    target.streaming = True
    metadata = anyio.Event()

    async def location() -> tuple[str, str]:
        metadata.set()
        return "https://example.test/", "Example"

    monkeypatch.setattr(target, "location", location)

    class Control:
        async def wait(self, timeout: float) -> BrowserCommand:
            await metadata.wait()
            return GIVE

    await held(
        BrowseSession(target),
        Control(),
        frames,
        call_id="call",
        by=None,
        by_user_id=None,
        remember=None,
    )
    assert target.shots == 0
    assert frames.of("browser_frame")[0].url == "https://example.test/"


async def test_metadata_updates_are_not_repeated_for_an_unchanged_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, frames = _FakePage(), _Frames()
    checked_twice = anyio.Event()
    calls = 0

    async def location() -> tuple[str, str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            checked_twice.set()
        return "https://example.test/", "Example"

    monkeypatch.setattr(target, "location", location)

    class Control:
        async def wait(self, timeout: float) -> BrowserCommand:
            await checked_twice.wait()
            return GIVE

    with anyio.fail_after(1):
        await held(
            BrowseSession(target),
            Control(),
            frames,
            call_id="call",
            by=None,
            by_user_id=None,
            remember=None,
        )
    assert len([frame for frame in frames.of("browser_frame") if frame.url]) == 1


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:pass@example.test/",
        "https://",
        "http://[",
        "https://example.test:broken/",
        "https://example.test:0/",
    ],
)
async def test_manual_addresses_are_validated_at_the_wire_boundary(url: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BrowserCommand(type="navigate", url=url)


async def test_optional_address_and_valid_port_remain_supported() -> None:
    assert BrowserCommand(type="navigate", url=None).url is None
    assert (
        BrowserCommand(type="navigate", url="http://example.test:8080/").url
        == "http://example.test:8080/"
    )


async def test_malformed_provider_history_is_a_transport_error() -> None:
    target, client = page()
    client.getNavigationHistory.return_value = {"entries": "bad"}
    with pytest.raises(EndpointError, match="invalid navigation history"):
        await target.back()


async def test_malformed_history_addresses_are_refused_without_crashing() -> None:
    target, client = page()
    client.getNavigationHistory.return_value = {
        "currentIndex": 1,
        "entries": [{"id": 1, "url": "http://["}] * 2,
    }
    with pytest.raises(StaleElement, match="history entry"):
        await target.back()


async def test_reading_resumes_an_existing_direct_preview() -> None:
    from tests.test_browser_use import _direct, _Opener, _toolset

    target = _FakePage()
    tools = _toolset(_Opener(target), preview=True)
    frames = _Frames()
    try:
        await _direct(tools, "browser_open", {"url": "https://example.test/"}, sink=frames)
        assert target.streaming
        await tools.stop_watching()
        assert not target.streaming
        await _direct(tools, "browser_read", sink=frames)
        assert target.streaming
    finally:
        await tools.close()


async def test_reading_an_existing_tab_without_a_direct_view_does_not_start_a_preview() -> None:
    from tests.test_browser_use import _direct, _Opener, _toolset

    target = _FakePage()
    tools = _toolset(_Opener(target))
    await tools.open(_Opener(target))
    try:
        report = await _direct(tools, "browser_read")
        assert report.startswith("PAGE:")
        assert not target.streaming
    finally:
        await tools.close()


@pytest.mark.parametrize("resize", [False, True])
async def test_interrupted_replay_does_not_skip_to_the_next_cached_action(resize: bool) -> None:
    from app.agents.capabilities.browser_use._plans import PlanStep
    from tests.test_browser_use import DONE, _element, _policy, _snapshot

    target = _FakePage(_snapshot(_element(0, label="First"), _element(1, label="Second")))

    class Control(_Control):
        polls = 0

        async def poll(self) -> BrowserCommand | None:
            self.polls += 1
            if self.polls == 2:
                return BrowserCommand(type="resize", width=800, height=600) if resize else TAKE
            return None

    async def decide(*args: object) -> _loop.Step:
        return DONE

    result = await _loop.run_browse(
        task="Two dependent clicks",
        session=BrowseSession(target),
        decide=decide,
        policy=_policy(max_steps=3),
        call_id="call",
        control=Control(GIVE),
        plan=tuple(
            PlanStep(op="click", at="example.test/page", role="button", label=label)
            for label in ("First", "Second")
        ),
    )
    assert result.outcome == "done"
    assert not any(action.startswith("click:") for action in target.done)
    assert result.replayed == 0


@pytest.mark.parametrize(
    "failure", [EndpointError("closed"), DomainRefused("Outside allowed domains")]
)
async def test_closing_a_failed_page_keeps_its_last_confirmed_location(
    failure: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.capabilities.browser_use._direct import close_view
    from tests.test_browser_use import _snapshot

    page, frames = _FakePage(), _Frames()
    monkeypatch.setattr(page, "location", AsyncMock(side_effect=failure))
    await close_view(
        DirectView("call", frames, None, None, None, True), BrowseSession(page, last=_snapshot())
    )
    assert frames.of("browser_finished")[0].url == "https://example.test/page"


@pytest.mark.parametrize("chat_present", [False, True])
async def test_live_images_require_a_viewer_even_when_chat_buffers_events(
    monkeypatch: pytest.MonkeyPatch,
    chat_present: bool,
) -> None:
    from uuid import uuid4

    from app.agents.browser_events import BrowserEvent
    from app.agents.capabilities.browser_use._toolset import _live
    from app.agents.deps import AgentDeps
    from app.services import live_browse

    clock = [0.0]
    viewers = AsyncMock(return_value=False)
    publish = AsyncMock()
    chat = AsyncMock(return_value=True) if chat_present else None
    monkeypatch.setattr(live_browse, "available", lambda: True)
    monkeypatch.setattr(live_browse, "open_view", AsyncMock())
    monkeypatch.setattr(live_browse, "has_viewers", viewers)
    monkeypatch.setattr(live_browse, "publish", publish)
    monkeypatch.setattr(
        "app.agents.capabilities.browser_use._toolset.time.monotonic", lambda: clock[0]
    )
    sink, _, _ = await _live(
        AgentDeps(organization_id=uuid4(), run_id=uuid4(), browser_events=chat), "call", "task"
    )
    assert sink is not None
    image = BrowserEvent(kind="browser_frame", call_id="call", step=0, image="jpeg")
    assert not await sink(image)
    publish.assert_not_awaited()
    metadata = BrowserEvent(
        kind="browser_frame", call_id="call", step=0, url="https://example.test/"
    )
    assert not await sink(metadata)
    publish.assert_awaited_once()
    assert viewers.await_count == 1
    viewers.return_value = True
    clock[0] = 2.0
    assert await sink(image)
    assert publish.await_count == 2
    assert viewers.await_count == 2
    if chat is not None:
        assert chat.await_count == 1


async def test_held_preview_recovers_after_a_temporary_metadata_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, frames = _FakePage(), _Frames()
    recovered = anyio.Event()
    calls = 0

    async def location() -> tuple[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EndpointError("Context is being replaced")
        return "https://example.test/recovered", "Recovered"

    async def emit(event: _loop.BrowserEvent) -> bool:
        await frames(event)
        if event.image is not None:
            recovered.set()
        return True

    class Control:
        async def wait(self, timeout: float) -> BrowserCommand:
            await recovered.wait()
            return GIVE

    monkeypatch.setattr(target, "location", location)
    with anyio.fail_after(2):
        await held(
            BrowseSession(target),
            Control(),
            emit,
            call_id="call",
            by=None,
            by_user_id=None,
            remember=None,
        )
    assert calls >= 2
    assert frames.of("browser_control_error")[0].detail == "Context is being replaced"
    assert frames.of("browser_frame")[0].url == "https://example.test/recovered"
    assert target.shots == 1


async def test_held_preview_does_not_capture_for_a_disconnected_viewer() -> None:
    target = _FakePage()
    checked = anyio.Event()

    async def emit(event: _loop.BrowserEvent) -> bool:
        if event.kind == "browser_frame":
            checked.set()
        return False

    class Control:
        async def wait(self, timeout: float) -> BrowserCommand:
            await checked.wait()
            return GIVE

    await held(
        BrowseSession(target),
        Control(),
        emit,
        call_id="call",
        by=None,
        by_user_id=None,
        remember=None,
    )
    assert target.shots == 0
