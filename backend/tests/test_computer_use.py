"""Computer use: a desktop operated through screenshots, the mouse and the keyboard.

What matters here is what the model is refused - a click off the screenshot, an
action before it has looked, more actions than the run allows, a daemon nobody
vetted - and that every point it names lands where it meant on a screen of a
different size.
"""

import io
import sys
import types
from collections.abc import MutableSequence, Sequence
from typing import Any, Literal
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr, ValidationError
from pydantic_ai import BinaryContent, ModelRetry
from pydantic_ai._run_context import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.computer_use import (
    ComputerUse,
    ComputerUseConfig,
    _daemon_url_form,
    _session,
    validate_daemon_url,
)
from app.agents.capabilities.computer_use._actions import (
    Click,
    Drag,
    Key,
    Move,
    Screen,
    Scroll,
    TypeText,
    Wait,
    describe,
    points_of,
    to_native,
)
from app.agents.capabilities.computer_use._backends import (
    MISSING_EXTRA,
    Capture,
    ComputerError,
    DaemonComputer,
    E2BComputer,
    E2BSettings,
    open_e2b,
    png_size,
    x11_keys,
    xdotool,
)
from app.agents.capabilities.computer_use._toolset import ToolPolicy, build_toolset, fit
from app.agents.capabilities.media import CONVERSATION_RESOURCE, ORGANIZATION_RESOURCE
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES, _computer_use_problems

pytestmark = pytest.mark.anyio


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "navy").save(out, format="PNG")
    return out.getvalue()


class _Desktop:
    """A desktop that records what it was told and answers with a blank screen."""

    def __init__(
        self,
        *,
        size: tuple[int, int] = (2560, 1600),
        native: tuple[int, int] = (1280, 800),
        refuses: str | None = None,
        blind: bool = False,
    ) -> None:
        self.label = "Test desktop"
        self.image = _png(*size)
        self.native = native
        self.refuses = refuses
        self.blind = blind
        self.performed: list[Any] = []
        self.captures = 0

    async def capture(self) -> Capture:
        self.captures += 1
        if self.blind:
            raise ComputerError("The desktop did not return a screenshot.")
        return Capture(image=self.image, width=self.native[0], height=self.native[1])

    async def perform(self, action: Any) -> None:
        if action.action == self.refuses:
            raise ComputerError("no such window")
        self.performed.append(action)


class _Frames:
    def __init__(self) -> None:
        self.events: list[BrowserEvent] = []

    async def __call__(self, event: BrowserEvent) -> bool:
        self.events.append(event)
        return True

    def kinds(self) -> list[str]:
        return [event.kind for event in self.events]


def _ctx(frames: _Frames | None = None, *, retries: int = 0) -> RunContext[AgentDeps]:
    ctx = RunContext(
        deps=AgentDeps(browser_events=frames, run_id=uuid4()),
        model=TestModel(),
        usage=RunUsage(),
        tool_call_id="call-1",
    )
    ctx.max_retries = retries
    return ctx


def _tools(desktop: Any, policy: ToolPolicy | None = None) -> dict[str, Any]:
    async def factory() -> Any:
        if isinstance(desktop, Exception):
            raise desktop
        return desktop

    toolset = build_toolset(factory, policy or ToolPolicy())
    return {name: tool.function for name, tool in toolset.tools.items()}


class TestCoordinates:
    """The model answers in the screenshot's pixels; the desktop moves in its own."""

    SCREEN = Screen(width=1280, height=800, native_width=2560, native_height=1600)

    def test_a_point_is_scaled_into_the_desktops_space(self):
        assert self.SCREEN.to_native(640, 400) == (1280, 800)

    def test_the_far_edge_stays_on_the_screen(self):
        assert self.SCREEN.to_native(1279, 799) == (2558, 1598)
        assert Screen(10, 10, 15, 15).to_native(9, 9) == (14, 14)

    def test_contains_only_points_on_the_screenshot(self):
        assert self.SCREEN.contains(0, 0)
        assert not self.SCREEN.contains(1280, 10)
        assert not self.SCREEN.contains(10, 800)

    def test_every_point_of_an_action_is_moved_and_nothing_else(self):
        drag = to_native(Drag(x=10, y=20, to_x=30, to_y=40), self.SCREEN)
        assert drag == Drag(x=20, y=40, to_x=60, to_y=80)
        click = to_native(Click(x=1, y=2, count=2), self.SCREEN)
        assert click == Click(x=2, y=4, count=2)
        typed = TypeText(text="hi")
        assert to_native(typed, self.SCREEN) is typed

    def test_points_of_names_each_point_an_action_touches(self):
        assert points_of(Drag(x=1, y=2, to_x=3, to_y=4)) == [(1, 2), (3, 4)]
        assert points_of(Scroll(x=5, y=6)) == [(5, 6)]
        assert points_of(Key(keys="enter")) == []


class TestTheLivePanelsWords:
    @pytest.mark.parametrize(
        ("action", "expected"),
        [
            (Click(x=1, y=2), ("CLICK", "(1, 2)")),
            (Click(x=1, y=2, count=2, button="right"), ("DOUBLE_CLICK", "(1, 2) (right)")),
            (Move(x=3, y=4), ("MOVE", "(3, 4)")),
            (Drag(x=1, y=2, to_x=3, to_y=4), ("DRAG", "(1, 2) → (3, 4)")),
            (Scroll(x=1, y=2, direction="up", amount=5), ("SCROLL", "up 5 at (1, 2)")),
            (TypeText(text="hello"), ("TYPE", "hello")),
            (Key(keys="ctrl+c"), ("KEY", "ctrl+c")),
            (Wait(seconds=1.5), ("WAIT", "1.5s")),
        ],
    )
    def test_each_action_is_described(self, action: Any, expected: tuple[str, str]):
        assert describe(action) == expected

    def test_long_typed_text_is_cut_short(self):
        _, target = describe(TypeText(text="x" * 100))
        assert target == "x" * 57 + "..."


class TestX11:
    def test_png_size_reads_the_header(self):
        assert png_size(_png(30, 20)) == (30, 20)

    def test_something_that_is_not_a_png_is_refused(self):
        with pytest.raises(ComputerError, match="not a screenshot"):
            png_size(b"<html>")

    def test_key_names_are_spelled_the_way_xdotool_wants(self):
        assert x11_keys("ctrl + Shift+t") == "ctrl+shift+t"
        assert x11_keys("cmd+space") == "super+space"
        assert x11_keys("Enter") == "Return"
        assert x11_keys("F5") == "F5"

    def test_a_chord_of_nothing_is_refused(self):
        with pytest.raises(ComputerError, match="names no key"):
            x11_keys(" + ")

    @pytest.mark.parametrize(
        ("action", "command"),
        [
            (
                Click(x=1, y=2, count=2, button="right"),
                "xdotool mousemove --sync 1 2 click --repeat 2 3",
            ),
            (Move(x=1, y=2), "xdotool mousemove --sync 1 2"),
            (
                Drag(x=1, y=2, to_x=3, to_y=4),
                "xdotool mousemove --sync 1 2 mousedown 1 mousemove --sync 3 4 mouseup 1",
            ),
            (
                Scroll(x=1, y=2, direction="left", amount=4),
                "xdotool mousemove --sync 1 2 click --repeat 4 6",
            ),
            (Key(keys="alt+f4"), "xdotool key -- alt+f4"),
            (Wait(), None),
        ],
    )
    def test_each_action_becomes_one_command(self, action: Any, command: str | None):
        assert xdotool(action) == command

    def test_typed_text_cannot_escape_into_the_shell(self):
        assert (
            xdotool(TypeText(text="a'; rm -rf / #"))
            == "xdotool type --delay 12 -- 'a'\"'\"'; rm -rf / #'"
        )


def _daemon(handler: Any) -> DaemonComputer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DaemonComputer("http://desk:8765/", "tok", client=client)


class TestTheDaemon:
    async def test_a_screenshot_carries_the_space_the_pointer_moves_in(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                content=_png(2880, 1800),
                headers={"x-platform": "macOS", "x-screen-width": "1440", "x-screen-height": "900"},
            )

        desktop = _daemon(handler)
        capture = await desktop.capture()

        assert (capture.width, capture.height, desktop.label) == (1440, 900, "macOS")
        assert str(seen[0].url) == "http://desk:8765/screenshot"
        assert seen[0].headers["authorization"] == "Bearer tok"

    async def test_without_headers_the_picture_is_the_space(self):
        desktop = _daemon(lambda request: httpx.Response(200, content=_png(64, 48)))
        capture = await desktop.capture()
        assert (capture.width, capture.height, desktop.label) == (64, 48, "Desktop")

    async def test_an_action_is_sent_as_the_daemon_reads_it(self):
        bodies: list[bytes] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.content)
            return httpx.Response(200, json={"ok": True})

        await _daemon(handler).perform(Key(keys="enter"))
        assert bodies == [b'{"actions":[{"action":"key","keys":"enter"}]}']

    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (httpx.Response(401), "refused this deployment's token"),
            (
                httpx.Response(400, json={"error": "unknown action"}),
                "refused the action: unknown action",
            ),
            (httpx.Response(400, json={"done": 0}), "HTTP 400"),
            (httpx.Response(500, text="boom"), "HTTP 500"),
        ],
    )
    async def test_a_refusal_is_told_to_the_model_in_a_sentence(
        self, response: httpx.Response, message: str
    ):
        with pytest.raises(ComputerError, match=message):
            await _daemon(lambda request: response).perform(Wait())

    async def test_an_unreachable_daemon_says_so_and_nothing_else(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused to http://desk:8765", request=request)

        with pytest.raises(ComputerError) as raised:
            await _daemon(handler).capture()
        assert (
            str(raised.value)
            == "The desktop could not be reached. It may be stopped or restarting."
        )

    def test_a_default_client_is_made_when_none_is_given(self):
        assert DaemonComputer("http://desk", "tok")._client is not None


class _Result:
    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout


class _Sandbox:
    """The two halves of an E2B sandbox the backend touches."""

    def __init__(self, *, fails: bool = False) -> None:
        self.commands = self
        self.files = self
        self.ran: list[tuple[str, dict[str, str]]] = []
        self.fails = fails
        self.killed = False
        self.sandbox_id = "sbx-1"

    def run(self, cmd: str, *, envs: dict[str, str] | None = None, timeout: float) -> _Result:
        if self.fails:
            raise RuntimeError("sandbox gone")
        self.ran.append((cmd, envs or {}))
        return _Result()

    def kill(self) -> None:
        self.killed = True

    def read(self, path: str, format: Literal["bytes"]) -> bytearray:
        return bytearray(_png(1024, 768))


class TestE2BDesktop:
    async def test_a_screenshot_is_taken_on_the_sandboxes_display(self):
        sandbox = _Sandbox()
        capture = await E2BComputer(sandbox).capture()

        assert (capture.width, capture.height) == (1024, 768)
        assert sandbox.ran[0][0].startswith("scrot --overwrite --pointer ")
        assert sandbox.ran[0][1] == {"DISPLAY": ":0"}

    async def test_an_action_runs_xdotool_and_a_wait_runs_nothing(self):
        sandbox = _Sandbox()
        desktop = E2BComputer(sandbox)
        await desktop.perform(Click(x=5, y=6))
        await desktop.perform(Wait(seconds=0.01))

        assert [cmd for cmd, _ in sandbox.ran] == [
            "xdotool mousemove --sync 5 6 click --repeat 1 1"
        ]

    async def test_a_failing_sandbox_is_a_sentence_for_the_model(self):
        desktop = E2BComputer(_Sandbox(fails=True))
        with pytest.raises(ComputerError, match="did not return a screenshot"):
            await desktop.capture()
        with pytest.raises(ComputerError, match="refused the click action"):
            await desktop.perform(Click(x=1, y=1))


class _SandboxClass:
    """Stands in for `e2b.Sandbox`: what was asked of it, and the sandboxes it handed out."""

    existing: Sequence[Any] = ()
    calls: MutableSequence[tuple[str, dict[str, Any]]] = []
    made: MutableSequence[_Sandbox] = []
    boot_fails = False

    class _Page:
        def __init__(self, items: Sequence[Any]) -> None:
            self.has_next = bool(items)
            self._items = items

        def next_items(self) -> Sequence[Any]:
            return self._items

    @classmethod
    def list(cls, **kwargs: Any) -> Any:
        cls.calls.append(("list", kwargs))
        return cls._Page(cls.existing)

    @classmethod
    def connect(cls, sandbox_id: str, **kwargs: Any) -> _Sandbox:
        cls.calls.append(("connect", {"sandbox_id": sandbox_id, **kwargs}))
        return _Sandbox()

    @classmethod
    def create(cls, **kwargs: Any) -> _Sandbox:
        cls.calls.append(("create", kwargs))
        cls.made.append(_Sandbox(fails=cls.boot_fails))
        return cls.made[-1]


@pytest.fixture
def e2b_sdk(monkeypatch: pytest.MonkeyPatch) -> type[_SandboxClass]:
    _SandboxClass.existing = ()
    _SandboxClass.calls = []
    _SandboxClass.made = []
    _SandboxClass.boot_fails = False
    monkeypatch.setitem(
        sys.modules,
        "e2b",
        types.SimpleNamespace(Sandbox=_SandboxClass, SandboxQuery=lambda metadata: metadata),
    )
    return _SandboxClass


class TestOpeningAnE2BDesktop:
    SETTINGS = E2BSettings(api_key="e2b_key", session="org:conv", timeout_seconds=600)

    async def test_the_first_turn_creates_a_desktop_tagged_with_its_session(self, e2b_sdk: Any):
        await open_e2b(self.SETTINGS)

        kind, kwargs = e2b_sdk.calls[-1]
        assert kind == "create"
        assert kwargs["metadata"] == {"agenticos_session": "org:conv"}
        assert (kwargs["timeout"], kwargs["template"]) == (600, "desktop")
        [(boot, _)] = e2b_sdk.made[0].ran
        assert "Xvfb :0 -ac -screen 0 1280x800x24" in boot
        assert "startxfce4" in boot

    async def test_a_desktop_that_does_not_come_up_is_killed_not_left_running(self, e2b_sdk: Any):
        e2b_sdk.boot_fails = True
        with pytest.raises(ComputerError, match="could not be started"):
            await open_e2b(self.SETTINGS)
        assert e2b_sdk.made[0].killed

    async def test_the_next_turn_finds_the_same_desktop(self, e2b_sdk: Any):
        e2b_sdk.existing = [types.SimpleNamespace(sandbox_id="sbx-7")]
        await open_e2b(self.SETTINGS)

        assert e2b_sdk.calls[0][1]["query"] == {"agenticos_session": "org:conv"}
        assert e2b_sdk.calls[-1] == (
            "connect",
            {"sandbox_id": "sbx-7", "timeout": 600, "api_key": "e2b_key"},
        )

    async def test_without_the_extra_the_model_is_told_what_to_install(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setitem(sys.modules, "e2b", None)
        with pytest.raises(ComputerError, match="computer"):
            await open_e2b(self.SETTINGS)
        assert "--extra computer" in MISSING_EXTRA

    async def test_a_refusal_from_e2b_names_the_key_and_the_limits(self, e2b_sdk: Any, monkeypatch):
        def refuse(**kwargs: Any) -> Any:
            raise RuntimeError("401 invalid api key e2b_key")

        monkeypatch.setattr(e2b_sdk, "list", staticmethod(refuse))
        with pytest.raises(ComputerError) as raised:
            await open_e2b(self.SETTINGS)
        assert "e2b_key" not in str(raised.value)
        assert "Check the E2B key" in str(raised.value)


class TestFit:
    def test_a_large_screen_is_shrunk_to_the_bound_keeping_its_shape(self):
        image, screen = fit(Capture(image=_png(2560, 1600), width=1280, height=800), 1280, 800)

        assert screen == Screen(width=1280, height=800, native_width=1280, native_height=800)
        assert Image.open(io.BytesIO(image)).format == "JPEG"

    def test_a_small_screen_is_not_enlarged(self):
        _, screen = fit(Capture(image=_png(800, 600), width=800, height=600), 1280, 800)
        assert (screen.width, screen.height) == (800, 600)


class TestTheTools:
    async def test_a_screenshot_is_shown_to_the_model_and_the_person(self):
        frames = _Frames()
        desktop = _Desktop()
        answer = await _tools(desktop)["computer_screenshot"](_ctx(frames))

        assert isinstance(answer[1], BinaryContent)
        assert answer[1].media_type == "image/jpeg"
        assert "1280x800" in answer[0]
        assert frames.kinds() == ["browser_opened", "browser_frame"]
        assert frames.events[0].title == "Test desktop"
        assert (frames.events[1].image or "").startswith("data:image/jpeg;base64,")

    async def test_the_panel_is_opened_once_and_keyed_on_the_run(self):
        frames = _Frames()
        tools = _tools(_Desktop())
        ctx = _ctx(frames)
        await tools["computer_screenshot"](ctx)
        await tools["computer_act"](ctx, [Click(x=10, y=10)])

        assert frames.kinds().count("browser_opened") == 1
        assert {event.call_id for event in frames.events} == {f"computer-{ctx.deps.run_id}"}
        assert frames.kinds()[-1] == "browser_finished"
        assert frames.events[-1].outcome == "done"

    async def test_actions_land_where_the_model_pointed_on_the_real_screen(self):
        desktop = _Desktop(size=(2560, 1600), native=(1440, 900))
        tools = _tools(desktop)
        ctx = _ctx()
        await tools["computer_screenshot"](ctx)
        answer = await tools["computer_act"](
            ctx, [Click(x=640, y=400), TypeText(text="hi"), Wait(seconds=0.01)]
        )

        assert [(a.x, a.y) for a in desktop.performed[:1]] == [(720, 450)]
        assert len(desktop.performed) == 3
        assert answer[0].startswith("Ran 3 of 3 action(s).")
        assert isinstance(answer[1], BinaryContent)

    async def test_acting_before_looking_is_refused(self):
        desktop = _Desktop()
        answer = await _tools(desktop)["computer_act"](_ctx(), [Click(x=1, y=1)])

        assert "Call `computer_screenshot` first" in answer
        assert desktop.performed == []

    @pytest.mark.security
    async def test_a_point_off_the_screenshot_is_refused_before_anything_runs(self):
        desktop = _Desktop()
        tools = _tools(desktop)
        ctx = _ctx()
        await tools["computer_screenshot"](ctx)
        answer = await tools["computer_act"](
            ctx, [Click(x=5, y=5), Drag(x=1, y=1, to_x=1280, to_y=1)]
        )

        assert "Action 2 (drag) names (1280, 1)" in answer
        assert desktop.performed == []

    async def test_an_empty_batch_is_steered_while_retries_remain(self):
        with pytest.raises(ModelRetry, match="at least one action"):
            await _tools(_Desktop())["computer_act"](_ctx(retries=1), [])

    async def test_a_batch_over_the_per_call_limit_is_refused(self):
        tools = _tools(_Desktop(), ToolPolicy(max_actions_per_call=2))
        answer = await tools["computer_act"](_ctx(), [Wait(), Wait(), Wait()])
        assert "at most 2 actions per call" in answer

    @pytest.mark.security
    async def test_the_run_stops_at_its_action_budget(self):
        desktop = _Desktop()
        tools = _tools(desktop, ToolPolicy(max_actions=3, max_actions_per_call=2))
        ctx = _ctx()
        await tools["computer_screenshot"](ctx)
        await tools["computer_act"](ctx, [Wait(seconds=0.01), Wait(seconds=0.01)])
        answer = await tools["computer_act"](ctx, [Wait(seconds=0.01), Wait(seconds=0.01)])

        assert "may take 3 desktop actions per run and has taken 2" in answer
        assert len(desktop.performed) == 2

    async def test_the_first_failing_action_stops_the_rest(self):
        frames = _Frames()
        desktop = _Desktop(refuses="type")
        tools = _tools(desktop)
        ctx = _ctx(frames)
        await tools["computer_screenshot"](ctx)
        answer = await tools["computer_act"](
            ctx, [Click(x=1, y=1), TypeText(text="x"), Key(keys="enter")]
        )

        assert "Ran 1 of 3 action(s). Action 2 (type) failed: no such window" in answer[0]
        assert len(desktop.performed) == 1
        assert frames.events[-1].outcome == "failed"
        assert [e.operation for e in frames.events if e.kind == "browser_step"] == ["CLICK", "TYPE"]

    async def test_a_desktop_that_cannot_be_opened_is_a_sentence(self):
        frames = _Frames()
        answer = await _tools(ComputerError("no desktop"))["computer_screenshot"](_ctx(frames))

        assert answer == "no desktop"
        assert frames.kinds() == ["browser_finished"]

    async def test_a_screenshot_lost_after_acting_still_reports_the_actions(self):
        desktop = _Desktop()
        tools = _tools(desktop)
        ctx = _ctx()
        await tools["computer_screenshot"](ctx)
        desktop.blind = True
        answer = await tools["computer_act"](ctx, [Wait(seconds=0.01)])

        assert answer == "Ran 1 of 1 action(s).\nThe desktop did not return a screenshot."

    async def test_without_preview_nothing_is_sent_to_the_chat(self):
        frames = _Frames()
        await _tools(_Desktop(), ToolPolicy(preview=False))["computer_screenshot"](_ctx(frames))
        assert frames.events == []


class TestTheCapability:
    async def test_without_a_url_the_daemon_backend_says_what_to_set(self):
        with pytest.raises(ComputerError, match="daemon_url"):
            await ComputerUse(daemon_token="t")._open()

    async def test_without_a_token_the_deployment_says_it_cannot_reach_a_desktop(self):
        with pytest.raises(ComputerError, match="COMPUTER_DAEMON_TOKEN"):
            await ComputerUse(daemon_url="http://desk:8765")._open()

    async def test_a_configured_daemon_is_reached_with_the_token(self):
        desktop = await ComputerUse(daemon_url="http://desk:8765", daemon_token="t")._open()
        assert isinstance(desktop, DaemonComputer)
        assert desktop._headers == {"Authorization": "Bearer t"}

    async def test_e2b_without_a_key_says_to_bind_one(self):
        with pytest.raises(ComputerError, match="no E2B key"):
            await ComputerUse(backend="e2b")._open()

    async def test_e2b_opens_the_sessions_desktop_at_the_policys_size(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        opened: list[E2BSettings] = []

        async def fake_open(settings: E2BSettings) -> Any:
            opened.append(settings)
            return "desktop"

        monkeypatch.setattr("app.agents.capabilities.computer_use._capability.open_e2b", fake_open)
        capability = ComputerUse(
            backend="e2b",
            e2b_key="k",
            e2b_session="org:conv",
            e2b_template="custom",
            e2b_timeout_seconds=120,
            policy=ToolPolicy(max_width=1024, max_height=768),
        )
        assert await capability._open() == "desktop"
        assert opened == [E2BSettings("k", "org:conv", "custom", 1024, 768, 120)]

    def test_the_toolset_is_built_once_and_the_instructions_distrust_the_screen(self):
        capability = ComputerUse(factory=lambda: None)  # ty: ignore[invalid-argument-type] - never awaited here
        assert capability.get_toolset() is capability.get_toolset()
        assert "untrusted" in capability.get_instructions()


def _build(
    config: dict[str, Any], *, secret: Any = None, resources: dict[str, Any] | None = None
) -> ComputerUse:
    definition = get("computer_use")
    capability = definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="computer_use", config=config),
            config=definition.validate_config(config),
            resources=resources or {},
            secret=secret,
        )
    )
    assert isinstance(capability, ComputerUse)
    return capability


class TestRegistration:
    @pytest.mark.security
    def test_acting_is_held_for_approval_and_looking_is_not(self):
        definition = get("computer_use")
        flags = {tool.id: tool.side_effecting for tool in definition.tools}

        # `computer_act` declares nothing of its own, so it takes the capability's flag.
        assert flags == {"computer_screenshot": False, "computer_act": None}
        assert definition.side_effecting
        assert definition.scopes <= DEFAULT_GRANTED_SCOPES

    def test_an_e2b_key_is_asked_for_only_by_the_e2b_backend(self):
        requirement = get("computer_use").secret
        assert requirement is not None
        assert requirement.required_when is not None
        assert (requirement.purpose, requirement.required_when.field) == ("e2b", "backend")
        assert requirement.required_when.equals == ("e2b",)

    def test_the_builder_hands_over_the_key_the_token_and_the_limits(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_TOKEN", "deployment-token")
        org, conversation = uuid4(), uuid4()
        capability = _build(
            {"backend": "e2b", "max_actions": 50, "max_actions_per_call": 5, "preview": False},
            secret=ApiKeySecret(api_key=SecretStr("e2b_" + "k" * 36)),
            resources={ORGANIZATION_RESOURCE: org, CONVERSATION_RESOURCE: conversation},
        )

        assert (capability.backend, capability.daemon_token) == ("e2b", "deployment-token")
        assert capability.e2b_key == "e2b_" + "k" * 36
        assert capability.e2b_session == f"{org}:{conversation}"
        assert capability.policy == ToolPolicy(
            max_actions=50, max_actions_per_call=5, preview=False
        )

    def test_an_empty_config_still_builds_and_has_no_key(self):
        capability = _build({})
        assert (capability.backend, capability.e2b_key, capability.daemon_url) == (
            "daemon",
            None,
            "",
        )

    @pytest.mark.security
    def test_two_tenants_never_share_a_desktop_and_a_run_without_a_thread_gets_its_own(self):
        conversation = uuid4()
        assert _session(uuid4(), conversation) != _session(uuid4(), conversation)
        assert _session(None, None).startswith("none:run-")
        assert _session(None, None) != _session(None, None)

    def test_a_batch_larger_than_the_run_is_refused(self):
        with pytest.raises(ValidationError, match="cannot be larger than max_actions"):
            ComputerUseConfig(max_actions=5, max_actions_per_call=10)


class TestTheDaemonAllowlist:
    """`daemon_url` is in the spec, and the deployment's token goes wherever it points."""

    def test_an_allowed_host_passes_case_folded(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [" Desk.Internal "])
        validate_daemon_url(ComputerUseConfig(daemon_url="http://desk.internal:8765"))

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("url", "message"),
        [
            ("", "needs a daemon_url"),
            ("ftp://desk.internal", "http or https URL"),
            ("http://desk.internal:99999", "invalid port"),
            (
                "http://attacker.example:8765",
                "does not allow computer use against 'attacker.example'",
            ),
        ],
    )
    def test_anything_else_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, url: str, message: str
    ):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", ["desk.internal"])
        with pytest.raises(UrlRefusedError, match=message):
            validate_daemon_url(ComputerUseConfig(daemon_url=url))

    def test_e2b_has_no_url_to_check(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [])
        validate_daemon_url(ComputerUseConfig(backend="e2b"))

    @pytest.mark.security
    def test_publish_names_an_unvetted_daemon(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [])
        problems = _computer_use_problems(ComputerUseConfig(daemon_url="http://desk:8765"))

        assert len(problems) == 1
        assert problems[0].startswith(
            "Computer use's desktop cannot be used: This deployment does not allow"
        )

    def test_publish_passes_a_vetted_daemon_and_ignores_other_capabilities(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", ["desk"])
        assert _computer_use_problems(ComputerUseConfig(daemon_url="http://desk:8765")) == []
        assert _computer_use_problems(None) == []

    def test_the_form_suggests_the_first_allowed_host(self, monkeypatch: pytest.MonkeyPatch):
        schema: dict[str, Any] = {}
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [" ", "desk"])
        _daemon_url_form(schema)
        assert schema["x-placeholder"] == "http://desk:8765"

        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [])
        _daemon_url_form(schema)
        assert schema["x-placeholder"] == "Set COMPUTER_DAEMON_ALLOWED_HOSTS first"
