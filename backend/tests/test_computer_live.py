"""Desktop take-over preserves the holder's identity and native coordinates."""

from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.browser_events import BrowserCommand
from app.agents.capabilities.computer_use import _live
from app.agents.capabilities.computer_use._actions import Click, Key, Screen, Scroll, TypeText
from app.agents.capabilities.computer_use._backends import ComputerError

pytestmark = pytest.mark.anyio
SCREEN = Screen(width=100, height=80, native_width=200, native_height=160)


def test_viewer_actions_are_scaled_and_bounded() -> None:
    assert _live.person_action(BrowserCommand(type="click", x=4000, y=4000), SCREEN) == Click(
        x=198, y=158
    )
    assert _live.person_action(BrowserCommand(type="type", text="private"), SCREEN) == TypeText(
        text="private"
    )
    assert _live.person_action(BrowserCommand(type="key", key="ArrowLeft"), SCREEN) == Key(
        keys="left"
    )
    for dy, direction in [(5000, "down"), (-1, "up")]:
        action = _live.person_action(BrowserCommand(type="scroll", dy=dy), SCREEN)
        assert isinstance(action, Scroll) and action.direction == direction
    assert _live.person_action(BrowserCommand(type="resize"), SCREEN) is None


async def test_only_take_over_is_taken_from_the_waiting_queue() -> None:
    assert await _live.take_over_waiting(None) is None
    control = MagicMock(
        poll=AsyncMock(side_effect=[BrowserCommand(type="click"), BrowserCommand(type="take_over")])
    )
    received = await _live.take_over_waiting(control)
    assert received is not None and received.type == "take_over"
    control.poll = AsyncMock(return_value=None)
    assert await _live.take_over_waiting(control) is None


async def test_other_viewers_cannot_act_or_release_the_desktop() -> None:
    commands = [
        BrowserCommand(type="click", x=2, y=3, by_user_id="stranger"),
        BrowserCommand(type="give_back", by_user_id="stranger"),
        BrowserCommand(type="type", text="private", by_user_id="owner"),
        BrowserCommand(type="click", x=1, y=1, by_user_id="owner"),
        BrowserCommand(type="give_back", by_user_id="owner"),
    ]
    control = MagicMock(wait=AsyncMock(side_effect=commands))
    computer = MagicMock(
        label="Desktop", perform=AsyncMock(side_effect=[ComputerError("denied"), None])
    )
    look = AsyncMock(
        side_effect=[
            (b"jpeg", SCREEN),
            (b"jpeg", SCREEN),
            ComputerError("frame refused"),
            (b"jpeg", SCREEN),
            (b"jpeg", SCREEN),
        ]
    )
    emit = AsyncMock()
    await _live.held(
        computer,
        control,
        BrowserCommand(type="take_over", by_user_id="owner"),
        look=look,
        emit=emit,
        call_id="call",
        step=1,
    )
    assert computer.perform.await_count == 2
    assert computer.perform.await_args_list[0].args == (TypeText(text="private"),)
    events = [call.args[0] for call in emit.await_args_list]
    assert events[0].kind == "browser_held" and events[-1].kind == "browser_released"
    assert all(event.reason is None for event in events)


async def test_local_computer_uses_the_paired_session_and_native_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64
    from io import BytesIO
    from uuid import uuid4

    from PIL import Image
    from pydantic_ai.workspaces import Workspace

    from app.agents.capabilities.computer_use import _backends
    from app.agents.capabilities.computer_use._actions import Launch, Wait
    from app.schemas.local_target import LocalTarget
    from app.services.device_hub import DeviceCallFailed, DeviceWorkspace

    user, session = uuid4(), uuid4()
    workspace = Workspace(DeviceWorkspace(session, user, LocalTarget(folder="/approved")))
    computer = _backends.open_local_desktop(workspace)
    buffer = BytesIO()
    Image.new("RGB", (100, 80)).save(buffer, format="PNG")
    call = AsyncMock(
        return_value={
            "data": base64.b64encode(buffer.getvalue()).decode(),
            "platform": "macos",
            "width": 200,
            "height": 160,
        }
    )
    monkeypatch.setattr(_backends, "call", call)
    screenshot = await computer.capture()
    assert (screenshot.width, screenshot.height) == (200, 160)
    assert computer.label == "macos"
    assert call.call_args.args == (session, "screen.capture", {})
    call.return_value = {"data": base64.b64encode(buffer.getvalue()).decode()}
    screenshot = await computer.capture()
    assert (screenshot.width, screenshot.height) == (100, 80)
    await computer.perform(Click(x=20, y=10))
    assert call.call_args.args[1] == "screen.act"
    calls = call.await_count
    with pytest.raises(ComputerError, match="cannot open applications by name"):
        await computer.perform(Launch(app="Safari"))
    with pytest.raises(ComputerError, match="cannot open applications by name"):
        await computer.apps()
    assert call.await_count == calls
    sleep = AsyncMock()
    monkeypatch.setattr(_backends.anyio, "sleep", sleep)
    await computer.perform(Wait(seconds=0.5))
    sleep.assert_awaited_once_with(0.5)
    await computer.close()
    call.side_effect = DeviceCallFailed(message="refused")
    await computer.close()
    with pytest.raises(ComputerError, match="desktop app"):
        _backends.open_local_desktop(Workspace(MagicMock()))


@pytest.mark.parametrize(
    "failure, message",
    [("offline", "not connected"), ("timeout", "in time"), ("refused", "refused")],
)
async def test_local_screen_failures_have_actionable_errors(
    monkeypatch: pytest.MonkeyPatch, failure: str, message: str
) -> None:
    from uuid import uuid4

    from app.agents.capabilities.computer_use import _backends
    from app.services.device_hub import DeviceCallFailed, DeviceCallTimedOut, DeviceUnavailable

    error = (
        DeviceUnavailable(message="offline")
        if failure == "offline"
        else DeviceCallTimedOut(message="late")
        if failure == "timeout"
        else DeviceCallFailed(message="refused")
    )
    monkeypatch.setattr(_backends, "call", AsyncMock(side_effect=error))
    with pytest.raises(ComputerError, match=message):
        await _backends.LocalComputer(uuid4()).capture()


@pytest.mark.parametrize(
    "backend,on_device,key",
    [
        ("local", False, ""),
        ("auto", True, ""),
        ("e2b", False, "tenant-key"),
        ("auto", False, "tenant-key"),
    ],
)
async def test_the_capability_selects_the_chosen_native_or_e2b_desktop(
    monkeypatch: pytest.MonkeyPatch,
    backend: Literal["local", "auto", "e2b"],
    on_device: bool,
    key: str,
) -> None:
    from uuid import uuid4

    from pydantic_ai.workspaces import Workspace
    from pydantic_ai_backends import StateBackend

    from app.agents.capabilities.computer_use import ComputerUse, _capability
    from app.schemas.local_target import LocalTarget
    from app.services.device_hub import DeviceWorkspace

    workspace = Workspace(
        DeviceWorkspace(uuid4(), uuid4(), LocalTarget(folder="/approved"))
        if on_device
        else StateBackend()
    )
    desktop = MagicMock()
    native, hosted = MagicMock(return_value=desktop), AsyncMock(return_value=desktop)
    monkeypatch.setattr(_capability, "open_local_desktop", native)
    monkeypatch.setattr(_capability, "open_e2b_desktop", hosted)
    result = await ComputerUse(backend=backend, daemon_token=key)._open(workspace)
    assert result is desktop
    if key:
        hosted.assert_awaited_once_with(key, width=1280, height=800)
        native.assert_not_called()
    else:
        native.assert_called_once_with(workspace)
        hosted.assert_not_called()


@pytest.mark.parametrize(
    ("backend", "on_device", "launch", "launcher"),
    [
        ("auto", True, False, True),
        ("local", False, False, True),
        ("auto", False, True, False),
        ("sandbox", False, True, False),
        ("daemon", True, True, True),
    ],
)
def test_launch_is_recommended_only_where_the_desktop_has_it(
    backend: Literal["auto", "local", "sandbox", "daemon"],
    on_device: bool,
    launch: bool,
    launcher: bool,
) -> None:
    """The desktop app refuses `launch`; told so up front, the model skips the refused round trip.

    A daemon may or may not launch, so the model is told to ask `computer_apps` first.
    """
    from uuid import uuid4

    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import RunContext
    from pydantic_ai.usage import RunUsage
    from pydantic_ai.workspaces import Workspace
    from pydantic_ai_backends import StateBackend

    from app.agents.capabilities.computer_use import ComputerUse
    from app.schemas.local_target import LocalTarget
    from app.services.device_hub import DeviceWorkspace

    workspace = Workspace(
        DeviceWorkspace(uuid4(), uuid4(), LocalTarget(folder="/approved"))
        if on_device
        else StateBackend()
    )
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage(), workspace=workspace)
    instructions = ComputerUse(backend=backend).get_instructions()(ctx)
    assert ("with the `launch` action" in instructions) is launch
    assert ("cmd+space" in instructions) is launcher
    assert ("do not work here" in instructions) is not launch
