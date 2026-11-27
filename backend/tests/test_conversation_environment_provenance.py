"""Activity routing uses actual owned views, never a delegate's parent or a duck-typed ID."""

from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.browser_events import BrowserEvent, with_environment
from app.agents.capabilities.browser_use._direct import DirectView, open_view
from app.agents.capabilities.browser_use._loop import BrowseSession
from app.services.conversation_environment_agent import AgentEnvironment, DrivenComputer, DrivenPage
from app.services.conversation_environment_driver import EnvironmentDriver
from tests.test_browser_use import DONE, _browse, _decider, _FakePage, _Frames
from tests.test_computer_use import _ctx, _Desktop, _toolset
from tests.test_computer_use import _Frames as DesktopFrames
from tests.test_conversation_environment_stream import case as case
from tests.test_conversation_environment_stream import run as run_stream

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def page_view(owned: bool):
    page = _FakePage()
    identity = uuid4()
    if owned:
        return DrivenPage(page, AsyncMock(spec=EnvironmentDriver), identity), identity
    page.environment_id = identity
    return page, None


@pytest.mark.parametrize("owned", [False, True])
async def test_browser_loop_frames_keep_actual_view_provenance_on_every_phase(owned):
    page, expected = page_view(owned)
    frames = _Frames()
    result = await _browse(BrowseSession(page=page), _decider(DONE), sink=frames)
    assert result.outcome == "done"
    assert frames.of("browser_opened") and frames.of("browser_finished")
    assert all(event.environment_id == expected for event in frames.frames)


@pytest.mark.parametrize("owned", [False, True])
async def test_direct_browser_open_and_followup_emit_only_the_actual_view_id(owned):
    page, expected = page_view(owned)
    frames = _Frames()
    view = DirectView("delegate-call", frames, None, None, None, False)
    await open_view(view, BrowseSession(page=page), "Inspect this page")
    await view.emit(
        BrowserEvent(kind="browser_frame", call_id="delegate-call", step=1, environment_id=uuid4())
    )
    assert len(frames.frames) == 2
    assert all(event.environment_id == expected for event in frames.frames)
    assert all(event.call_id == "delegate-call" for event in frames.frames)


@pytest.mark.parametrize("owned", [False, True])
async def test_real_desktop_toolset_preserves_actual_id_through_finished_after_detach(owned):
    desktop = _Desktop(size=(640, 480), native=(640, 480))
    identity = uuid4()
    owner = AsyncMock(spec=AgentEnvironment)
    owner.driver = AsyncMock(spec=EnvironmentDriver)
    view = DrivenComputer(desktop, owner, AsyncExitStack(), identity) if owned else desktop
    if not owned:
        desktop.environment_id = identity
    frames = DesktopFrames()
    tools = _toolset(view)
    async with tools:
        await tools.tools["computer_screenshot"].function(_ctx(frames))
    assert frames.kinds()[0] == "browser_opened"
    assert frames.kinds()[-1] == "browser_finished"
    assert all(event.environment_id == (identity if owned else None) for event in frames.events)
    assert tools.session.computer is None


async def test_nominal_owned_id_is_read_only_and_legacy_marker_is_actively_cleared():
    page, identity = page_view(True)
    with pytest.raises(AttributeError):
        page.environment_id = uuid4()
    event = BrowserEvent(kind="browser_opened", call_id="call", step=0, environment_id=identity)
    assert with_environment(event, SimpleNamespace(environment_id=identity)).environment_id is None
    assert with_environment(event, page).environment_id == identity
    assert BrowserEvent(kind="browser_opened", call_id="legacy", step=0).environment_id is None


async def test_owned_environment_socket_events_are_explicitly_bound_to_its_uuid(case):
    from fastapi import WebSocketDisconnect

    case.socket.receive_text.side_effect = WebSocketDisconnect()
    await run_stream(case)
    frames = [item["data"] for item in case.frames if item["type"] == "browser_event"]
    assert frames and all(frame["environment_id"] == str(case.identity) for frame in frames)
