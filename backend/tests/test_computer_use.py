"""Computer use: a desktop operated through screenshots, the mouse and the keyboard.

What matters here is what the model is refused - a click off the screenshot, an
action before it has looked, more actions than the run allows, a daemon nobody
vetted - and that every point it names lands where it meant on a screen of a
different size.
"""

import io
import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr, ValidationError
from pydantic_ai import Agent, BinaryContent, ModelRetry
from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturn,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import CommandResult, Workspace, WorkspaceError
from pydantic_ai_backends import StateBackend

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.approval import tool_needs_approval
from app.agents.capabilities.computer_use import (
    ComputerUse,
    ComputerUseConfig,
    _daemon_url_form,
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
    Capture,
    ComputerError,
    DaemonComputer,
    SandboxComputer,
    open_sandbox_desktop,
    png_size,
    x11_keys,
    xdotool,
)
from app.agents.capabilities.computer_use._toolset import (
    OUTPUT_DIR,
    SEEN,
    ComputerToolset,
    SavedScreenshot,
    Seen,
    ToolPolicy,
    build_toolset,
    fit,
)
from app.agents.deps import AgentDeps
from app.agents.ephemeral_media import EPHEMERAL, NOT_KEPT, dump_messages
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.config import settings
from app.core.sanitize import UrlRefusedError
from app.core.secret_kinds import ApiKeySecret, SecretKind
from app.services.agent_registry import (
    DEFAULT_GRANTED_SCOPES,
    _computer_use_problems,
    _computer_use_sandbox_problems,
)
from app.services.generated_media import load_generated_image
from tests.workspaces import ShellFailing, document_workspace

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
        self.closed = 0

    async def capture(self) -> Capture:
        self.captures += 1
        if self.blind:
            raise ComputerError("The desktop did not return a screenshot.")
        return Capture(image=self.image, width=self.native[0], height=self.native[1])

    async def perform(self, action: Any) -> None:
        if action.action == self.refuses:
            raise ComputerError("no such window")
        self.performed.append(action)

    async def close(self) -> None:
        self.closed += 1


class _Frames:
    def __init__(self, *, gone: bool = False) -> None:
        self.events: list[BrowserEvent] = []
        self.gone = gone
        """The reader closed the tab: every event is sent and none arrives."""

    async def __call__(self, event: BrowserEvent) -> bool:
        self.events.append(event)
        return not self.gone

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


def _said(answer: ToolReturn | str) -> tuple[str, BinaryContent]:
    """The text and the screenshot an answer showed the model."""
    assert isinstance(answer, ToolReturn)
    text, image = answer.return_value  # ty: ignore[not-iterable] - always a pair here
    assert isinstance(text, str)
    assert isinstance(image, BinaryContent)
    return text, image


def _seen(answer: ToolReturn | str) -> Seen:
    """What an answer recorded for a resumed run."""
    assert isinstance(answer, ToolReturn)
    return Seen.model_validate(answer.metadata[SEEN])


def _resumed(
    ctx: RunContext[AgentDeps],
    *,
    screen: Screen | None,
    actions_taken: int = 0,
    run_id: str | None = None,
) -> RunContext[AgentDeps]:
    """The context of a run resumed after a park, whose history ends on an earlier answer."""
    seen = Seen(
        run_id=run_id if run_id is not None else str(ctx.deps.run_id),
        screen=screen,
        actions_taken=actions_taken,
    )
    history: list[ModelMessage] = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="renamed_screenshot",
                    content="Test desktop.",
                    metadata={SEEN: seen.model_dump(mode="json")},
                ),
                ToolReturnPart(tool_name="other", content="unrelated", metadata={"x": 1}),
            ]
        )
    ]
    return replace(ctx, messages=history)


_SHOWN = Screen(width=1280, height=800, native_width=1440, native_height=900)
"""What a 2560x1600 capture of a 1440x900 desktop is shown to the model as."""


def _toolset(desktop: Any, policy: ToolPolicy | None = None) -> ComputerToolset:
    async def factory(workspace: Workspace) -> Any:
        if isinstance(desktop, Exception):
            raise desktop
        return desktop

    return build_toolset(factory, policy or ToolPolicy())


def _tools(desktop: Any, policy: ToolPolicy | None = None) -> dict[str, Any]:
    return {name: tool.function for name, tool in _toolset(desktop, policy).tools.items()}


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
        ],
    )
    def test_each_action_becomes_one_command(self, action: Any, command: str):
        assert xdotool(action) == command.split()

    def test_a_wait_is_no_command_at_all(self):
        assert xdotool(Wait()) is None

    def test_typed_text_is_one_argument_whatever_it_holds(self):
        text = "a'; rm -rf / #"
        assert xdotool(TypeText(text=text)) == ["xdotool", "type", "--delay", "12", "--", text]


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

    async def test_a_client_it_made_is_closed_and_one_it_was_handed_is_not(self):
        made = DaemonComputer("http://desk", "tok")
        handed = _daemon(lambda request: httpx.Response(200))

        await made.close()
        await handed.close()

        assert made._client.is_closed
        assert not handed._client.is_closed


class _Box:
    """A sandbox's shell: what it was asked to run, and what each command answers.

    Only the members the desktop touches - `run` makes it a `SupportsCommands`
    backend, and the screenshot comes back through `read_bytes`.
    """

    def __init__(
        self, *, exit_code: int = 0, stderr: str = "", fails: bool = False, attached: bool = True
    ) -> None:
        self.ran: list[tuple[Any, bool, dict[str, str]]] = []
        self.exit_code = exit_code
        self.stderr = stderr
        self.fails = fails
        self.attached = attached
        self.backend = self
        self.unreadable = False
        self.undeletable = False
        self.removed: list[str] = []

    async def run(
        self,
        command: Any,
        *,
        shell: bool = False,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if self.fails:
            raise WorkspaceError("sandbox gone")
        self.ran.append((command, shell, dict(env or {})))
        return CommandResult(exit_code=self.exit_code, stdout="", stderr=self.stderr)

    async def read_bytes(self, path: str) -> bytes:
        if self.unreadable:
            raise WorkspaceError(f"shell filesystem read failed for {path!r}")
        return _png(1024, 768)

    async def remove(self, path: str) -> None:
        if self.undeletable:
            raise WorkspaceError(f"shell filesystem remove failed for {path!r}")
        self.removed.append(path)


def _on(box: _Box) -> SandboxComputer:
    return SandboxComputer(box)  # ty: ignore[invalid-argument-type] - the members it uses


class TestTheSandboxDesktop:
    async def test_a_screenshot_is_taken_on_the_sandboxes_display_and_read_back(self):
        box = _Box()
        capture = await _on(box).capture()

        assert (capture.width, capture.height) == (1024, 768)
        [(argv, shell, env)] = box.ran
        assert argv[:3] == ["scrot", "--overwrite", "--pointer"]
        assert argv[3].startswith("/tmp/agenticos-screen-")  # noqa: S108 - a path in the sandbox
        assert (shell, env) == (False, {"DISPLAY": ":0"})
        assert box.removed == [argv[3]]

    @pytest.mark.security
    async def test_a_screenshot_is_not_left_in_the_sandbox_even_unread(self):
        """A later shell there - a delegate's, the next run's - finds no picture of the screen."""
        box = _Box()
        box.unreadable = True
        with pytest.raises(ComputerError):
            await _on(box).capture()
        assert box.removed == [box.ran[0][0][3]]

    async def test_a_screenshot_that_cannot_be_removed_is_still_shown(
        self, caplog: pytest.LogCaptureFixture
    ):
        box = _Box()
        box.undeletable = True
        capture = await _on(box).capture()
        assert (capture.width, capture.height) == (1024, 768)
        assert "sandbox screenshot not removed: WorkspaceError" in caplog.text

    async def test_the_sandbox_desktop_holds_nothing_to_close(self):
        box = _Box()
        await _on(box).close()
        assert box.ran == []

    async def test_two_desktops_on_one_sandbox_do_not_share_a_screenshot(self):
        box = _Box()
        await _on(box).capture()
        await _on(box).capture()
        assert box.ran[0][0][3] != box.ran[1][0][3]

    async def test_an_action_runs_xdotool_and_a_wait_runs_nothing(self):
        box = _Box()
        desktop = _on(box)
        await desktop.perform(Click(x=5, y=6))
        await desktop.perform(Wait(seconds=0.01))

        assert [argv for argv, _, _ in box.ran] == [
            ["xdotool", "mousemove", "--sync", "5", "6", "click", "--repeat", "1", "1"]
        ]

    async def test_a_refused_command_tells_the_model_what_the_desktop_said(self):
        with pytest.raises(ComputerError, match="refused to run the click action: no display"):
            await _on(_Box(exit_code=1, stderr="no display\n")).perform(Click(x=1, y=1))
        with pytest.raises(ComputerError, match="refused to take a screenshot: exit 2"):
            await _on(_Box(exit_code=2)).capture()

    async def test_a_sandbox_that_is_gone_is_a_sentence_for_the_model(self):
        with pytest.raises(ComputerError, match="could not take a screenshot"):
            await _on(_Box(fails=True)).capture()

    async def test_a_screenshot_that_cannot_be_read_back_is_a_sentence(self):
        box = _Box()
        box.unreadable = True
        with pytest.raises(ComputerError, match="did not return the screenshot it took"):
            await _on(box).capture()


class TestOpeningTheSandboxDesktop:
    @staticmethod
    async def _open(workspace: Any) -> SandboxComputer:
        return await open_sandbox_desktop(workspace, width=1024, height=768)

    async def test_the_desktop_is_started_at_the_policys_size_unless_it_runs(self):
        box = _Box()
        assert isinstance(await self._open(box), SandboxComputer)

        [(script, shell, _)] = box.ran
        assert shell
        # Left alone only when both the display and the session that keeps the
        # desktop running are up; each is started on its own when it is not.
        assert script.startswith(
            "xdpyinfo -display :0 >/dev/null 2>&1 && pgrep -x xfce4-session >/dev/null && exit 0\n"
        )
        assert "if ! xdpyinfo -display :0 >/dev/null 2>&1; then\n" in script
        assert "Xvfb :0 -ac -screen 0 1024x768x24" in script
        assert "if ! pgrep -x xfce4-session >/dev/null; then\n" in script
        assert "startxfce4" in script

    @pytest.mark.parametrize("workspace", [_Box(attached=False), document_workspace()])
    async def test_a_run_without_a_sandbox_that_runs_commands_says_what_to_add(
        self, workspace: Any
    ):
        with pytest.raises(ComputerError, match="Add the Sandbox capability"):
            await self._open(workspace)

    @pytest.mark.parametrize(
        ("box", "message"),
        [
            (_Box(exit_code=3), "Run the agent's sandbox on the `desktop` runtime"),
            (_Box(exit_code=1), "did not start"),
            (_Box(fails=True), "could not be reached to start its desktop"),
        ],
    )
    async def test_a_desktop_that_does_not_come_up_says_why(self, box: _Box, message: str):
        with pytest.raises(ComputerError, match=message):
            await self._open(box)


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
        ctx = _ctx(frames)
        text, image = _said(await _tools(desktop)["computer_screenshot"](ctx))

        assert image.media_type == "image/jpeg"
        assert "1280x800" in text
        assert frames.kinds() == ["browser_opened", "browser_frame"]
        assert frames.events[0].title == "Test desktop"
        assert (frames.events[1].image or "").startswith("data:image/jpeg;base64,")

    async def test_one_window_is_named_after_the_first_look_and_closed_with_the_run(self):
        """The chat draws a window under the tool call whose id it carries.

        So every frame of the run goes to the first screenshot's window, and it is
        finished once, when the run leaves the toolset - not after each call, which
        would end the window while the agent is still working.
        """
        frames = _Frames()
        toolset = _toolset(_Desktop())
        tools = {name: tool.function for name, tool in toolset.tools.items()}
        async with toolset:
            async with toolset:
                await tools["computer_screenshot"](_ctx(frames))
                await tools["computer_act"](
                    replace(_ctx(frames), tool_call_id="call-2"), [Click(x=10, y=10)]
                )
            assert "browser_finished" not in frames.kinds()

        assert frames.kinds().count("browser_opened") == 1
        assert {event.call_id for event in frames.events} == {"call-1"}
        assert frames.kinds()[-1] == "browser_finished"
        assert frames.kinds().count("browser_finished") == 1
        assert frames.events[-1].outcome == "done"

        await toolset.session.close_view()
        assert frames.kinds().count("browser_finished") == 1

    async def test_the_desktop_is_let_go_once_when_the_run_leaves(self):
        desktop = _Desktop()
        toolset = _toolset(desktop)
        tools = {name: tool.function for name, tool in toolset.tools.items()}
        async with toolset:
            await tools["computer_screenshot"](_ctx())
            assert desktop.closed == 0
        assert desktop.closed == 1

        await toolset.session.close_desktop()
        assert desktop.closed == 1

    async def test_a_reader_who_left_is_sent_no_more_frames(self):
        """The run goes on; screenshots are no longer encoded for a socket nobody reads."""
        frames = _Frames(gone=True)
        tools = _tools(_Desktop())
        await tools["computer_screenshot"](_ctx(frames))
        await tools["computer_act"](_ctx(frames), [Click(x=10, y=10)])

        assert frames.kinds() == ["browser_opened"]

    async def test_a_call_without_an_id_still_gets_one_window(self):
        frames = _Frames()
        await _tools(_Desktop())["computer_screenshot"](replace(_ctx(frames), tool_call_id=None))
        assert frames.events[0].call_id.startswith("computer-")

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
        assert _said(answer)[0].startswith("Ran 3 of 3 action(s).")
        assert _seen(answer) == Seen(run_id=str(ctx.deps.run_id), screen=_SHOWN, actions_taken=3)

    async def test_an_approved_batch_runs_from_the_json_it_was_approved_as(self):
        desktop = _Desktop()
        tools = _tools(desktop)
        ctx = _ctx()
        await tools["computer_screenshot"](ctx)
        answer = await tools["computer_act"](
            ctx, [{"action": "click", "x": 640, "y": 400}, {"action": "type", "text": "hi"}]
        )

        assert [a.action for a in desktop.performed] == ["click", "type"]
        assert _said(answer)[0].startswith("Ran 2 of 2 action(s).")

    async def test_a_run_resumed_after_approval_acts_on_the_screen_it_was_shown(self):
        """Approval resumes the run as a new one, which has not looked yet.

        Refusing there sent the model back to look and ask again, so no approved
        batch ever ran. The screen is measured, found the shape the model saw
        before the park, the window opens under the act, and the points are
        mapped as they were on that screenshot.
        """
        frames = _Frames()
        desktop = _Desktop(size=(2560, 1600), native=(1440, 900))
        ctx = _resumed(_ctx(frames), screen=_SHOWN)
        answer = await _tools(desktop)["computer_act"](ctx, [Click(x=640, y=400)])

        assert [(a.x, a.y) for a in desktop.performed] == [(720, 450)]
        assert _said(answer)[0].startswith("Ran 1 of 1 action(s).")
        assert frames.kinds()[:2] == ["browser_opened", "browser_frame"]
        assert {event.call_id for event in frames.events} == {"call-1"}

    @pytest.mark.security
    @pytest.mark.parametrize(
        "shown",
        [
            Screen(width=1280, height=800, native_width=2880, native_height=1800),
            Screen(width=1280, height=720, native_width=1920, native_height=1080),
        ],
        ids=["resolution", "aspect"],
    )
    async def test_a_resumed_batch_on_a_screen_that_changed_does_nothing(self, shown: Screen):
        """Points chosen on the old screenshot would land somewhere else on the new one.

        Mapped through the new screen they can stay in bounds and click what
        nobody approved, so the batch is refused and the new screenshot shown.
        """
        desktop = _Desktop(size=(2560, 1600), native=(1440, 900))
        ctx = _resumed(_ctx(), screen=shown)
        answer = await _tools(desktop)["computer_act"](ctx, [Click(x=640, y=400)])

        text, _ = _said(answer)
        assert text.startswith("Nothing was done: the screen changed since the screenshot")
        assert f"from {shown.native_width}x{shown.native_height} to 1440x900" in text
        assert desktop.performed == []
        assert _seen(answer).screen == _SHOWN

    @pytest.mark.security
    @pytest.mark.parametrize("screen", [None, "absent"], ids=["lost", "never-taken"])
    async def test_a_batch_with_no_screenshot_behind_it_is_refused(self, screen: str | None):
        """Coordinates nobody chose on a screenshot mean nothing.

        Either the history shows none - a compacted one, or a run that never
        looked - or the last answer lost its screenshot after acting.
        """
        desktop = _Desktop()
        ctx = _ctx(retries=1) if screen == "absent" else _resumed(_ctx(retries=1), screen=None)
        with pytest.raises(ModelRetry, match="Take a screenshot with `computer_screenshot` first"):
            await _tools(desktop)["computer_act"](ctx, [Click(x=1, y=1)])

        assert desktop.performed == []
        assert desktop.captures == 0

    @pytest.mark.security
    @pytest.mark.parametrize("failed", ["looking", "after-acting"])
    async def test_a_screenshot_that_failed_leaves_no_screen_to_act_on(self, failed: str):
        """The last screenshot shown stops counting once a capture is tried and fails.

        Points chosen on it would be aimed at whatever the failed capture would
        have shown - after a batch, a screen that batch changed.
        """
        desktop = _Desktop()
        tools = _tools(desktop)
        ctx = _ctx(retries=1)
        await tools["computer_screenshot"](ctx)
        desktop.blind = True
        if failed == "looking":
            await tools["computer_screenshot"](ctx)
        else:
            await tools["computer_act"](ctx, [Click(x=10, y=10)])
        desktop.blind = False
        performed = len(desktop.performed)

        with pytest.raises(ModelRetry, match="Take a screenshot with `computer_screenshot` first"):
            await tools["computer_act"](ctx, [Click(x=10, y=10)])
        assert len(desktop.performed) == performed

    @pytest.mark.security
    async def test_every_run_of_one_built_agent_has_a_session_of_its_own(self):
        """A delegate's agent is built once per parent run and run for each delegation.

        The second run was shown no screenshot, so its points are refused rather
        than aimed by the first run's, and it starts its action count at zero.
        """
        desktop = _Desktop()
        script = [
            [ToolCallPart("computer_screenshot", {})],
            [ToolCallPart("computer_act", {"actions": [{"action": "click", "x": 10, "y": 10}]})],
            [TextPart("first done")],
            [ToolCallPart("computer_act", {"actions": [{"action": "click", "x": 10, "y": 10}]})],
            [TextPart("second done")],
        ]

        async def factory(workspace: Workspace) -> Any:
            return desktop

        def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=script.pop(0))

        agent = Agent(
            FunctionModel(model),
            deps_type=AgentDeps,
            capabilities=[ComputerUse(factory=factory, policy=ToolPolicy(max_actions=1))],
        )
        await agent.run("first", deps=AgentDeps(run_id=uuid4()))
        second = await agent.run("second", deps=AgentDeps(run_id=uuid4()))

        assert len(desktop.performed) == 1
        refused = [
            part.model_response()
            for message in second.new_messages()
            for part in getattr(message, "parts", [])
            if part.part_kind == "retry-prompt"
        ]
        assert len(refused) == 1
        assert "Take a screenshot with `computer_screenshot` first" in refused[0]

    @pytest.mark.security
    async def test_a_resumed_batch_off_the_screen_is_still_refused(self):
        desktop = _Desktop(size=(2560, 1600), native=(1440, 900))
        answer = await _tools(desktop)["computer_act"](
            _resumed(_ctx(), screen=_SHOWN), [Click(x=1280, y=1)]
        )

        assert "names (1280, 1), which is off the 1280x800 screenshot" in answer
        assert desktop.performed == []

    async def test_a_desktop_that_cannot_be_measured_is_a_sentence(self):
        answer = await _tools(ComputerError("no desktop"))["computer_act"](
            _resumed(_ctx(), screen=_SHOWN), [Wait()]
        )
        assert answer == "no desktop"

    @pytest.mark.security
    async def test_the_action_budget_is_the_runs_across_approvals(self):
        """Every approval resumes the run with a new session, which used to count from zero.

        So an agent gated on approval took its whole budget again after each one.
        """
        desktop = _Desktop(size=(2560, 1600), native=(1440, 900))
        tools = _tools(desktop, ToolPolicy(max_actions=3, max_actions_per_call=2))
        ctx = _resumed(_ctx(), screen=_SHOWN, actions_taken=2)

        answer = await tools["computer_act"](ctx, [Wait(seconds=0.01), Wait(seconds=0.01)])

        assert "may take 3 desktop actions per run and has taken 2" in answer
        assert desktop.performed == []

    async def test_a_screenshot_carries_the_runs_count_forward(self):
        """A resumed run that only looks still records what the run has spent."""
        ctx = _resumed(_ctx(), screen=_SHOWN, actions_taken=2)
        answer = await _tools(_Desktop())["computer_screenshot"](ctx)

        assert _seen(answer).actions_taken == 2

    async def test_an_earlier_runs_actions_are_not_this_runs(self):
        """A later turn is a new run, with its whole budget."""
        desktop = _Desktop(size=(2560, 1600), native=(1440, 900))
        tools = _tools(desktop, ToolPolicy(max_actions=3, max_actions_per_call=2))
        ctx = _resumed(_ctx(), screen=_SHOWN, actions_taken=3, run_id=str(uuid4()))

        answer = await tools["computer_act"](ctx, [Wait(seconds=0.01)])

        assert _said(answer)[0].startswith("Ran 1 of 1 action(s).")
        assert _seen(answer).actions_taken == 1

    async def test_an_unreadable_record_is_no_record(self):
        ctx = replace(
            _ctx(retries=1),
            messages=[
                ModelRequest(
                    parts=[
                        ToolReturnPart(tool_name="x", content="", metadata={SEEN: {"screen": 1}})
                    ]
                )
            ],
        )
        with pytest.raises(ModelRetry, match="Take a screenshot"):
            await _tools(_Desktop())["computer_act"](ctx, [Wait()])

    async def test_the_model_is_shown_a_screenshot_nobody_keeps(self):
        _, image = _said(await _tools(_Desktop())["computer_screenshot"](_ctx()))
        assert image.identifier.startswith(EPHEMERAL)

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
        toolset = _toolset(desktop)
        tools = {name: tool.function for name, tool in toolset.tools.items()}
        ctx = _ctx(frames)
        await tools["computer_screenshot"](ctx)
        answer = await tools["computer_act"](
            ctx, [Click(x=1, y=1), TypeText(text="x"), Key(keys="enter")]
        )
        await toolset.session.close_view()

        assert "Ran 1 of 3 action(s). Action 2 (type) failed: no such window" in _said(answer)[0]
        assert len(desktop.performed) == 1
        assert frames.events[-1].outcome == "failed"
        assert frames.events[-1].detail == "Action 2 (type) failed: no such window"
        assert [e.operation for e in frames.events if e.kind == "browser_step"] == ["CLICK", "TYPE"]

    async def test_a_desktop_that_cannot_be_opened_is_a_sentence(self):
        frames = _Frames()
        toolset = _toolset(ComputerError("no desktop"))
        answer = await toolset.tools["computer_screenshot"].function(_ctx(frames))
        await toolset.session.close_view()

        assert answer == "no desktop"
        assert frames.events == []

    async def test_a_screenshot_lost_after_acting_still_reports_the_actions(self):
        frames = _Frames()
        desktop = _Desktop()
        toolset = _toolset(desktop)
        ctx = _ctx(frames)
        await toolset.tools["computer_screenshot"].function(ctx)
        desktop.blind = True
        answer = await toolset.tools["computer_act"].function(ctx, [Wait(seconds=0.01)])
        await toolset.session.close_view()

        assert isinstance(answer, ToolReturn)
        assert (
            answer.return_value == "Ran 1 of 1 action(s).\nThe desktop did not return a screenshot."
        )
        assert _seen(answer) == Seen(run_id=str(ctx.deps.run_id), screen=None, actions_taken=1)
        assert frames.events[-1].outcome == "failed"

    async def test_without_preview_nothing_is_sent_to_the_chat(self):
        frames = _Frames()
        await _tools(_Desktop(), ToolPolicy(preview=False))["computer_screenshot"](_ctx(frames))
        assert frames.events == []


class TestAcrossAPark:
    @pytest.mark.security
    async def test_a_stored_park_keeps_the_geometry_and_the_count_and_not_the_picture(self):
        """What a resumed run reads back is the run's own stored messages.

        A real run takes the screenshot and acts; its messages are stored the way
        an approval parks them; a new capability - the resumed run's - acts on
        what it reads back, with the screenshot's bytes gone from the store.
        """
        desktop = _Desktop(size=(2560, 1600), native=(1440, 900))

        async def factory(workspace: Workspace) -> Any:
            return desktop

        def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart("computer_screenshot", {})])
            if len(messages) == 3:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "computer_act", {"actions": [{"action": "wait", "seconds": 0.01}]}
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart("parked")])

        run_id = uuid4()
        agent = Agent(
            FunctionModel(model),
            deps_type=AgentDeps,
            capabilities=[ComputerUse(factory=factory, policy=ToolPolicy(max_actions=2))],
        )
        result = await agent.run("open the report", deps=AgentDeps(run_id=run_id))
        stored = dump_messages(result.all_messages())

        assert NOT_KEPT in json.dumps(stored)
        assert all(
            not (isinstance(item, dict) and item.get("kind") == "binary")
            for message in stored
            for part in message["parts"]
            for item in (part.get("content") if isinstance(part.get("content"), list) else [])
        )

        resumed = replace(
            _ctx(),
            deps=AgentDeps(run_id=run_id),
            messages=ModelMessagesTypeAdapter.validate_python(stored),
        )
        answer = await _tools(desktop, ToolPolicy(max_actions=2))["computer_act"](
            resumed, [Wait(seconds=0.01), Wait(seconds=0.01)]
        )

        assert "may take 2 desktop actions per run and has taken 1" in answer


class TestSavingAScreenshot:
    """The screenshot the user keeps, as against the one the model looks at."""

    @pytest.fixture(autouse=True)
    def _media(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)

    @staticmethod
    def _ctx(
        organization_id: UUID | None, workspace: Workspace | None = None
    ) -> RunContext[AgentDeps]:
        ctx = RunContext(
            deps=AgentDeps(organization_id=organization_id), model=TestModel(), usage=RunUsage()
        )
        if workspace is not None:
            ctx.workspace = workspace
        return ctx

    @staticmethod
    async def _save(desktop: Any, ctx: RunContext[AgentDeps]) -> str:
        return await _tools(desktop)["computer_save_screenshot"](
            ctx, caption="The page after the click"
        )

    async def test_it_is_kept_at_full_resolution_and_drawn_in_the_chat(self):
        organization_id = uuid4()
        desktop = _Desktop()

        saved = SavedScreenshot.model_validate_json(
            await self._save(desktop, self._ctx(organization_id))
        )

        # The bytes as the desktop took them - 2560x1600, not the model's 1280x800.
        assert saved.filename is not None
        assert await load_generated_image(organization_id, saved.filename) == desktop.image
        assert saved.url == f"/api/v1/generated/{saved.filename}"
        assert (saved.kind, saved.width, saved.height) == ("desktop_screenshot", 2560, 1600)
        assert saved.caption == "The page after the click"
        assert saved.workspace_path is None

    async def test_it_is_written_into_an_open_workspace(self):
        document = StateBackend()
        desktop = _Desktop()

        saved = SavedScreenshot.model_validate_json(
            await self._save(desktop, self._ctx(uuid4(), document_workspace(document)))
        )

        assert saved.workspace_path == f"{OUTPUT_DIR}/{saved.filename}"
        assert document.read_bytes(saved.workspace_path) == desktop.image

    async def test_without_an_organization_only_the_workspace_has_it(self):
        document = StateBackend()

        saved = SavedScreenshot.model_validate_json(
            await self._save(_Desktop(), self._ctx(None, document_workspace(document)))
        )

        assert (saved.filename, saved.url) == (None, None)
        assert saved.workspace_path is not None
        assert saved.workspace_path.startswith(f"{OUTPUT_DIR}/screenshot-")

    async def test_a_workspace_that_cannot_take_it_names_no_path(self):
        saved = SavedScreenshot.model_validate_json(
            await self._save(_Desktop(), self._ctx(uuid4(), ShellFailing(document_workspace())))
        )

        assert saved.url is not None
        assert saved.workspace_path is None

    async def test_a_desktop_that_cannot_be_captured_is_a_sentence(self):
        answer = await self._save(_Desktop(blind=True), self._ctx(uuid4()))
        assert answer == "The desktop did not return a screenshot."


class TestTheCapability:
    @pytest.fixture(autouse=True)
    def desk_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", ["desk"])

    async def test_without_a_url_the_daemon_backend_says_what_to_set(self):
        with pytest.raises(ComputerError, match="daemon_url"):
            await ComputerUse(backend="daemon", daemon_token="t")._open(document_workspace())

    async def test_without_a_token_the_tool_says_where_one_comes_from(self):
        with pytest.raises(ComputerError, match="token from the organization's vault"):
            await ComputerUse(backend="daemon", daemon_url="http://desk:8765")._open(
                document_workspace()
            )

    @pytest.mark.security
    async def test_a_host_taken_off_the_allowlist_after_publish_is_not_sent_the_token(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Publish checked the host once; the operator's list is what holds now."""
        capability = ComputerUse(backend="daemon", daemon_url="http://desk:8765", daemon_token="t")
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [])

        with pytest.raises(ComputerError, match="does not allow computer use against 'desk'"):
            await capability._open(document_workspace())

    async def test_a_configured_daemon_is_reached_with_the_token(self):
        desktop = await ComputerUse(
            backend="daemon", daemon_url="http://desk:8765", daemon_token="t"
        )._open(document_workspace())
        assert isinstance(desktop, DaemonComputer)
        assert desktop._headers == {"Authorization": "Bearer t"}

    async def test_the_sandbox_desktop_is_opened_in_the_runs_workspace_at_the_policys_size(self):
        box = _Box()
        capability = ComputerUse(policy=ToolPolicy(max_width=1024, max_height=768))
        desktop = await capability._open(box)  # ty: ignore[invalid-argument-type] - the members it uses

        assert isinstance(desktop, SandboxComputer)
        assert "Xvfb :0 -ac -screen 0 1024x768x24" in box.ran[0][0]

    async def test_the_toolset_hands_the_runs_workspace_to_the_desktop(self):
        frames = _Frames()
        box = _Box()
        toolset = ComputerUse().get_toolset()
        ctx = _ctx(frames)
        ctx.workspace = box  # ty: ignore[invalid-assignment] - the members it uses
        await toolset.tools["computer_screenshot"].function(ctx)  # ty: ignore[unresolved-attribute] - a ComputerToolset
        await toolset.session.close_view()  # ty: ignore[unresolved-attribute] - a ComputerToolset

        assert [argv[0] for argv, _, _ in box.ran[1:]] == ["scrot"]

    def test_the_toolset_is_built_once_and_the_instructions_distrust_the_screen(self):
        capability = ComputerUse(factory=lambda workspace: None)  # ty: ignore[invalid-argument-type] - never awaited here
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
    def test_acting_can_be_held_for_approval_without_holding_looking(self):
        """Approval is the agent owner's choice, and it can stop at the clicks.

        Gating `computer_act` alone keeps the model able to look before it asks,
        which is what makes an approval request something a person can judge.
        """
        definition = get("computer_use")
        flags = {tool.id: tool.side_effecting for tool in definition.tools}

        # `computer_act` declares nothing of its own, so it takes the capability's flag.
        assert flags == {
            "computer_screenshot": False,
            "computer_act": None,
            "computer_save_screenshot": False,
        }
        assert definition.side_effecting
        assert definition.scopes <= DEFAULT_GRANTED_SCOPES

        def held(binding: CapabilityBindingSpec) -> set[str]:
            return {
                tool.id
                for tool in definition.tools
                if tool_needs_approval(tool=tool, binding=binding)
            }

        assert held(CapabilityBindingSpec(id="computer_use")) == set()
        gated = CapabilityBindingSpec(id="computer_use", tool_approval={"computer_act": "required"})
        assert held(gated) == {"computer_act"}

    def test_the_sandbox_is_the_default_and_nothing_is_asked_of_the_vault(self):
        definition = get("computer_use")
        assert ComputerUseConfig().desktop == "sandbox"
        assert not definition.needs_secret(ComputerUseConfig())

    @pytest.mark.security
    def test_a_daemon_needs_the_organizations_token_from_its_vault(self):
        """The token is what lets an organization drive a desktop, so it is the organization's.

        The allowlist is the deployment's, so any organization may name an allowed
        host; a deployment-wide token went with it and let one organization
        drive another's desktop.
        """
        definition = get("computer_use")
        assert definition.secret is not None
        assert definition.secret.kind == SecretKind.API_KEY
        assert definition.needs_secret(ComputerUseConfig(desktop="daemon"))
        assert not hasattr(settings, "COMPUTER_DAEMON_TOKEN")

    def test_where_the_desktop_is_is_asked_first_and_only_a_daemon_has_a_url(self):
        properties = ComputerUseConfig.model_json_schema()["properties"]
        assert next(iter(properties)) == "desktop"
        assert properties["desktop"]["enum"] == ["sandbox", "daemon"]
        assert properties["daemon_url"]["x-visible-when"] == {
            "field": "desktop",
            "equals": ["daemon"],
        }

    def test_the_builder_hands_over_the_bindings_token_and_the_limits(self):
        capability = _build(
            {
                "desktop": "daemon",
                "daemon_url": "http://desk:8765",
                "max_actions": 50,
                "max_actions_per_call": 5,
                "preview": False,
            },
            secret=ApiKeySecret(api_key=SecretStr("organization-token")),
        )

        assert (capability.backend, capability.daemon_url) == ("daemon", "http://desk:8765")
        assert capability.daemon_token == "organization-token"
        assert "organization-token" not in repr(capability)
        assert capability.policy == ToolPolicy(
            max_actions=50, max_actions_per_call=5, preview=False
        )

    def test_an_empty_config_builds_a_desktop_in_the_sandbox(self):
        capability = _build({})
        assert (capability.backend, capability.daemon_url, capability.daemon_token) == (
            "sandbox",
            "",
            "",
        )

    def test_a_batch_larger_than_the_run_is_refused(self):
        with pytest.raises(ValidationError, match="cannot be larger than max_actions"):
            ComputerUseConfig(max_actions=5, max_actions_per_call=10)


class TestTheDaemonAllowlist:
    """`daemon_url` is in the spec, and the binding's token goes wherever it points."""

    def test_an_allowed_host_passes_case_folded(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [" Desk.Internal "])
        validate_daemon_url(
            ComputerUseConfig(desktop="daemon", daemon_url="http://desk.internal:8765")
        )

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("url", "message"),
        [
            ("", "needs a daemon_url"),
            ("ftp://desk.internal", "http or https URL"),
            ("http://desk.internal:99999", "port must be a number"),
            ("http://desk.internal:8765?x=1", "no query or fragment"),
            ("http://desk.internal:8765/#top", "no query or fragment"),
            ("http://desk.internal:8765?", "no query or fragment"),
            ("http://user:secret@desk.internal:8765", "credentials out of the daemon_url"),
            ("http://token@desk.internal:8765", "credentials out of the daemon_url"),
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
            validate_daemon_url(ComputerUseConfig(desktop="daemon", daemon_url=url))

    @pytest.mark.security
    def test_a_secret_pasted_as_the_port_is_not_repeated(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", ["desk.internal"])
        with pytest.raises(UrlRefusedError) as refused:
            validate_daemon_url(
                ComputerUseConfig(
                    desktop="daemon", daemon_url="http://desk.internal:client_secret=sh-key"
                )
            )
        assert "sh-key" not in str(refused.value)
        assert "port must be a number" in str(refused.value)

    def test_the_sandbox_has_no_url_to_check(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [])
        validate_daemon_url(ComputerUseConfig(desktop="sandbox", daemon_url="http://anything"))

    @pytest.mark.security
    def test_publish_names_an_unvetted_daemon(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", [])
        problems = _computer_use_problems(
            ComputerUseConfig(desktop="daemon", daemon_url="http://desk:8765")
        )

        assert len(problems) == 1
        assert problems[0].startswith(
            "Computer use's desktop cannot be used: This deployment does not allow"
        )

    def test_publish_passes_a_vetted_daemon_and_ignores_other_capabilities(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", ["desk"])
        assert (
            _computer_use_problems(
                ComputerUseConfig(desktop="daemon", daemon_url="http://desk:8765")
            )
            == []
        )
        assert _computer_use_problems(None) == []

    @pytest.mark.security
    def test_the_form_names_no_allowed_host(self, monkeypatch: pytest.MonkeyPatch):
        """Every organization reads the catalog; the operator's desktops are not theirs to learn."""
        monkeypatch.setattr(settings, "COMPUTER_DAEMON_ALLOWED_HOSTS", ["private-desk.corp"])
        schema: dict[str, Any] = {}
        _daemon_url_form(schema)

        assert "private-desk" not in str(schema)
        assert "private-desk" not in str(ComputerUseConfig.model_json_schema())


class TestPublishingADesktopInTheSandbox:
    @staticmethod
    def _spec(*bindings: dict[str, Any]) -> AgentSpec:
        return AgentSpec.model_validate(
            {"name": "operator", "model_profile_id": str(uuid4()), "capabilities": list(bindings)}
        )

    @pytest.mark.parametrize(
        "sandbox",
        [None, {"id": "sandbox", "config": {"backend": "state"}}],
    )
    def test_a_desktop_in_a_sandbox_the_agent_does_not_have_is_refused(
        self, sandbox: dict[str, Any] | None
    ):
        bindings = [{"id": "computer_use"}] + ([sandbox] if sandbox else [])
        assert _computer_use_sandbox_problems(self._spec(*bindings)) == [
            "Computer use's desktop runs in the agent's sandbox, so it needs the Sandbox "
            "capability on a sandbox connection, on the 'desktop' runtime."
        ]

    def test_a_sandbox_connection_without_a_shell_tool_is_enough(self):
        spec = self._spec(
            {"id": "computer_use"},
            {"id": "sandbox", "config": {"backend": "service", "include_execute": False}},
        )
        assert _computer_use_sandbox_problems(spec) == []

    @pytest.mark.parametrize(
        "binding",
        [
            {"id": "computer_use", "config": {"desktop": "daemon"}},
            {"id": "computer_use", "enabled": False},
            {"id": "computer_use", "config": {"desktop": "cloud"}},
        ],
    )
    def test_a_daemon_a_disabled_binding_or_a_broken_config_is_not_asked(
        self, binding: dict[str, Any]
    ):
        assert _computer_use_sandbox_problems(self._spec(binding)) == []
