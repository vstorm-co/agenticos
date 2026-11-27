"""Environment sockets have stable identity and never become a provider proxy."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import pytest
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.conversation_environment import ConversationEnvironment
from app.schemas.conversation_environment import ConversationEnvironmentRead
from app.services import conversation_environment_stream as stream
from app.services.conversation_environment_resources import DesktopEnvironmentResource

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    identity, conversation, agent, owner, org = (uuid4() for _ in range(5))
    row = ConversationEnvironment(
        id=identity,
        organization_id=org,
        user_id=owner,
        conversation_id=conversation,
        agent_id=agent,
        state="ready",
        kind="desktop",
        resource_key="physical-screen",
        resource_ciphertext="sealed-handle",
    )
    ctx = AuthContext(user_id=owner, organization_id=org, role="member")
    read = ConversationEnvironmentRead(
        id=identity,
        kind="desktop",
        execution_target="agent",
        agent_id=agent,
        state="ready",
        session_lifetime="conversation",
        idle_seconds=900,
        control="none",
        can_control=True,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        refusal=None,
    )
    resource = DesktopEnvironmentResource(
        environment_id=identity,
        organization_id=org,
        backend="daemon",
        daemon_url="http://private-provider:8765",
        credential="private-token",
        width=1280,
        height=800,
    )
    resolved = SimpleNamespace(authority=SimpleNamespace(agent=SimpleNamespace(id=agent)))
    db = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(stream, "get_db_context", session)
    monkeypatch.setattr(stream, "authenticate_socket_key", AsyncMock(return_value=None))
    monkeypatch.setattr(
        stream, "authenticate_socket_token", AsyncMock(return_value=SimpleNamespace(id=owner))
    )
    monkeypatch.setattr(stream, "current_actor", AsyncMock(return_value=ctx))
    monkeypatch.setattr(stream.environments, "for_socket", AsyncMock(return_value=row))
    monkeypatch.setattr(
        stream.ConversationEnvironmentService,
        "live",
        AsyncMock(return_value=(row, resolved, resource)),
    )
    monkeypatch.setattr(stream.ConversationEnvironmentService, "read", AsyncMock(return_value=read))
    closed = []

    @asynccontextmanager
    async def view(_resource, _resolved):
        try:
            yield stream.runtime.DesktopEnvironmentView(AsyncMock(), 1280, 800)
        finally:
            closed.append(True)

    monkeypatch.setattr(stream.runtime, "open_view", view)
    monkeypatch.setattr(
        stream.runtime,
        "picture",
        AsyncMock(
            return_value=stream.runtime.EnvironmentPicture(image="data:image/jpeg;base64,AA==")
        ),
    )
    monkeypatch.setattr(stream.runtime, "perform", AsyncMock())
    socket = AsyncMock(spec=WebSocket)
    socket.application_state = socket.client_state = WebSocketState.CONNECTED
    frames = []

    async def send(text):
        frames.append(json.loads(text))

    socket.send_text.side_effect = send
    return SimpleNamespace(
        socket=socket,
        frames=frames,
        conversation=conversation,
        identity=identity,
        closed=closed,
        ctx=ctx,
        db=db,
        read=read,
        row=row,
        resolved=resolved,
        resource=resource,
    )


async def run(case):
    await stream.stream_environment(
        case.socket,
        auth_token="session-token",
        conversation_id=case.conversation,
        environment_id=case.identity,
        execution_target="agent",
    )


async def test_read_only_view_emits_stable_environment_id_and_disconnect_only_detaches(case):
    async def receive():
        await anyio.sleep_forever()

    async def send(text):
        frame = json.loads(text)
        case.frames.append(frame)
        if frame["type"] == "browser_event" and frame["data"]["kind"] == "browser_frame":
            raise WebSocketDisconnect()

    case.socket.receive_text.side_effect, case.socket.send_text.side_effect = receive, send
    await run(case)
    assert case.closed == [True]
    events = [frame["data"] for frame in case.frames if frame["type"] == "browser_event"]
    assert events and all(event["call_id"] == str(case.identity) for event in events)
    assert all(event["run_id"] is None for event in events)
    assert events[-1]["navigable"] is False
    assert "private-token" not in json.dumps(case.frames)
    assert "private-provider" not in json.dumps(case.frames)
    stream.runtime.perform.assert_not_awaited()


async def test_api_key_cannot_reuse_issuer_identity_after_successful_handshake(case):
    stream.authenticate_socket_key.return_value = SimpleNamespace(user_id=case.ctx.user_id)
    await run(case)
    stream.authenticate_socket_token.assert_not_awaited()
    stream.environments.for_socket.assert_not_awaited()
    case.socket.close.assert_awaited_once_with(
        code=4403, reason="The original environment is unavailable or access changed"
    )
    assert not case.frames and not case.closed


async def test_unknown_environment_is_refused_without_opening_provider(case):
    stream.environments.for_socket.return_value = None
    await run(case)
    assert not case.closed and not case.frames
    assert case.socket.close.await_args.kwargs["code"] == 4403


async def test_authority_revocation_closes_existing_view_and_sends_no_more_frames(case):
    stream.current_actor.side_effect = [case.ctx, AuthorizationError(message="Membership revoked")]

    async def receive():
        await anyio.sleep_forever()

    case.socket.receive_text.side_effect = receive
    await run(case)
    assert case.closed == [True]
    assert case.socket.close.await_args.kwargs["code"] == 4403
    stream.runtime.picture.assert_not_awaited()


async def test_uncontrolled_invalid_and_oversized_commands_never_reach_the_provider(case):
    commands = [
        "x" * 16385,
        "not JSON",
        json.dumps({"type": "click", "x": 0.2, "y": 0.2}),
        WebSocketDisconnect(),
    ]
    case.socket.receive_text.side_effect = commands
    await run(case)
    errors = [
        frame["data"]["detail"]
        for frame in case.frames
        if frame["type"] == "browser_event" and frame["data"]["kind"] == "browser_control_error"
    ]
    assert len(errors) == 3
    stream.runtime.perform.assert_not_awaited()
    assert case.closed == [True]


@pytest.fixture
def clock_case(case, monkeypatch):
    from app.services.conversation_environment_policy import EnvironmentNotReady

    now = datetime(2026, 11, 27, tzinfo=UTC)
    clock = SimpleNamespace(now=now, touches=[], driver=None)
    case.row.expires_at = now + timedelta(seconds=60)
    case.read.expires_at, case.read.idle_seconds = case.row.expires_at, 60

    async def live(_ctx, _conversation, _environment, _target, *, lock=False, touch=False):
        if clock.now >= case.row.expires_at:
            raise EnvironmentNotReady("environment_expired", "The idle window ended")
        if touch:
            assert lock, "Activity must be serialized with End before provider input"
            clock.touches.append(clock.now)
            case.row.expires_at = clock.now + timedelta(seconds=60)
            case.read.expires_at = case.row.expires_at
        return case.row, case.resolved, case.resource

    monkeypatch.setattr(stream.ConversationEnvironmentService, "live", AsyncMock(side_effect=live))

    class Driver:
        def __init__(self, _key, _ctx, _control, check):
            self.check = check
            self.control = _control
            self.closed = 0
            clock.driver = self

        async def acquire(self):
            await self.check(case.db)

        async def require(self):
            await self.check(case.db)

        async def close(self):
            self.closed += 1

    monkeypatch.setattr(stream, "EnvironmentDriver", Driver)
    return case, clock


async def test_human_control_heartbeats_cannot_prolong_idle_paid_resources(clock_case):
    from app.services.conversation_environment_policy import EnvironmentNotReady

    case, clock = clock_case
    start = clock.now
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps({"type": "take_over"})
        assert clock.driver is not None
        assert case.row.expires_at == start + timedelta(seconds=60)
        for elapsed in (15, 30, 45, 59):
            clock.now = start + timedelta(seconds=elapsed)
            await clock.driver.check(case.db)
        assert case.row.expires_at == start + timedelta(seconds=60)
        clock.now = start + timedelta(seconds=61)
        with pytest.raises(EnvironmentNotReady):
            await clock.driver.check(case.db)
        raise WebSocketDisconnect()

    case.socket.receive_text.side_effect = receive
    await run(case)
    assert clock.touches == [start]
    assert case.row.expires_at == start + timedelta(seconds=60)
    assert clock.driver.closed == 1
    stream.runtime.perform.assert_not_awaited()


async def test_actual_input_and_give_back_extend_idle_under_the_row_lock(clock_case):
    case, clock = clock_case
    start = clock.now
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps({"type": "take_over"})
        if calls == 2:
            clock.now = start + timedelta(seconds=30)
            return json.dumps({"type": "click", "x": 10, "y": 20})
        if calls == 3:
            assert case.row.expires_at == start + timedelta(seconds=90)
            clock.now = start + timedelta(seconds=89)
            return json.dumps({"type": "give_back"})
        assert case.row.expires_at == start + timedelta(seconds=149)
        raise WebSocketDisconnect()

    case.socket.receive_text.side_effect = receive
    await run(case)
    assert clock.touches == [start, start + timedelta(seconds=30), start + timedelta(seconds=89)]
    assert stream.runtime.perform.await_count == 1
    assert clock.driver.closed == 1


async def test_passive_frames_and_periodic_reauthentication_do_not_renew_idle(
    clock_case, monkeypatch
):
    case, clock = clock_case
    start = clock.now
    original_sleep = anyio.sleep

    async def tick(_seconds):
        clock.now += timedelta(seconds=31)
        await original_sleep(0)

    async def receive():
        await anyio.sleep_forever()

    monkeypatch.setattr(stream.anyio, "sleep", tick)
    monkeypatch.setattr(
        stream,
        "time",
        SimpleNamespace(monotonic=lambda: 1000 + (clock.now - start).total_seconds()),
    )
    case.socket.receive_text.side_effect = receive
    with anyio.fail_after(2):
        await run(case)
    assert clock.touches == []
    assert case.row.expires_at == start + timedelta(seconds=60)
    assert stream.runtime.picture.await_count == 2
    assert case.socket.close.await_args.kwargs["code"] == 4403


async def test_held_identity_acknowledges_only_this_sockets_successful_claim(clock_case):
    case, _clock = clock_case
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "take_over"}),
        json.dumps({"type": "give_back"}),
        WebSocketDisconnect(),
    ]
    await run(case)
    ownership = [
        frame["data"]
        for frame in case.frames
        if frame["type"] == "browser_event"
        and frame["data"]["kind"] in ("browser_held", "browser_released")
    ]
    assert [event["kind"] for event in ownership] == ["browser_held", "browser_released"]
    assert ownership[0]["by_user_id"] == str(case.ctx.subject_id)
    assert ownership[1]["by_user_id"] is None


async def test_refused_physical_claim_never_acknowledges_human_ownership(clock_case, monkeypatch):
    from app.core.exceptions import ConflictError

    case, _clock = clock_case
    monkeypatch.setattr(
        stream.EnvironmentDriver,
        "acquire",
        AsyncMock(side_effect=ConflictError(message="Already held")),
    )
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "take_over"}),
        WebSocketDisconnect(),
    ]
    await run(case)
    kinds = [frame["data"]["kind"] for frame in case.frames if frame["type"] == "browser_event"]
    assert "browser_held" not in kinds
    assert "browser_control_error" in kinds
    stream.runtime.perform.assert_not_awaited()


async def test_repeated_takeover_rechecks_the_existing_socket_lease_before_ack(
    clock_case, monkeypatch
):
    from app.core.exceptions import ConflictError

    case, _clock = clock_case
    require = AsyncMock(side_effect=ConflictError(message="Lease lost"))
    monkeypatch.setattr(stream.EnvironmentDriver, "require", require)
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "take_over"}),
        json.dumps({"type": "take_over"}),
        WebSocketDisconnect(),
    ]
    await run(case)
    held = [
        frame
        for frame in case.frames
        if frame["type"] == "browser_event" and frame["data"]["kind"] == "browser_held"
    ]
    assert len(held) == 1
    require.assert_awaited_once()


async def test_idle_browser_fit_uses_short_exclusive_lease_without_human_ack_or_idle_touch(
    clock_case,
):
    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    expires = case.row.expires_at
    resize = {"type": "resize", "width": 640, "height": 900, "scale": 2}
    case.socket.receive_text.side_effect = [
        json.dumps(resize),
        json.dumps({"type": "click", "x": 1, "y": 2}),
        WebSocketDisconnect(),
    ]
    await run(case)
    assert stream.runtime.perform.await_count == 1
    assert stream.runtime.perform.await_args.args[1].model_dump(include=set(resize)) == resize
    assert clock.driver.closed == 1 and clock.driver.control == "layout"
    assert clock.touches == [] and case.row.expires_at == expires
    kinds = [frame["data"]["kind"] for frame in case.frames if frame["type"] == "browser_event"]
    assert "browser_held" not in kinds
    assert "browser_control_error" in kinds, "Resizing does not grant permission to send input"


@pytest.mark.parametrize("control", ["agent", "human"])
async def test_viewer_fit_cannot_displace_a_busy_physical_driver(clock_case, monkeypatch, control):
    from app.core.exceptions import ConflictError

    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    case.read.control = control
    monkeypatch.setattr(
        stream.EnvironmentDriver, "acquire", AsyncMock(side_effect=ConflictError(message="Busy"))
    )
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "resize", "width": 640, "height": 900}),
        WebSocketDisconnect(),
    ]
    await run(case)
    assert clock.driver.closed == 1
    assert clock.touches == []
    stream.runtime.perform.assert_not_awaited()
    assert not any(
        frame["data"]["kind"] in ("browser_held", "browser_control_error")
        for frame in case.frames
        if frame["type"] == "browser_event"
    )
    assert case.frames[-1]["type"] == "environment_state" or any(
        frame["type"] == "environment_state" and frame["data"]["control"] == control
        for frame in case.frames
    )


async def test_view_only_browser_fit_does_not_claim_control(clock_case, monkeypatch):
    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    case.read.can_control = False
    acquire = AsyncMock()
    monkeypatch.setattr(stream.EnvironmentDriver, "acquire", acquire)
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "resize", "width": 640, "height": 900}),
        WebSocketDisconnect(),
    ]
    await run(case)
    acquire.assert_not_awaited()
    assert clock.driver is None and clock.touches == []
    stream.runtime.perform.assert_not_awaited()


async def test_browser_fit_provider_failure_releases_temporary_lease_and_hides_details(clock_case):
    from app.agents.capabilities.computer_use._backends import ComputerError

    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    stream.runtime.perform.side_effect = ComputerError("private-provider-secret")
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "resize", "width": 640, "height": 900}),
        WebSocketDisconnect(),
    ]
    await run(case)
    assert clock.driver.closed == 1 and clock.touches == []
    assert "private-provider-secret" not in json.dumps(case.frames)
    assert any(
        frame["data"]["kind"] == "browser_control_error"
        for frame in case.frames
        if frame["type"] == "browser_event"
    )


async def test_browser_fit_reuses_only_its_already_held_socket_lease(clock_case):
    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "take_over"}),
        json.dumps({"type": "resize", "width": 640, "height": 900}),
        WebSocketDisconnect(),
    ]
    await run(case)
    assert clock.driver.closed == 1
    assert len(clock.touches) == 1, "Automatic fit is not another paid idle extension"
    assert stream.runtime.perform.await_count == 1


async def test_desktop_fit_is_explicitly_unsupported_without_claiming_control(clock_case):
    case, clock = clock_case
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "resize", "width": 640, "height": 900}),
        WebSocketDisconnect(),
    ]
    await run(case)
    assert clock.driver is None and clock.touches == []
    stream.runtime.perform.assert_not_awaited()
    assert any(
        frame["data"]["kind"] == "browser_control_error"
        for frame in case.frames
        if frame["type"] == "browser_event"
    )


async def test_cancelling_viewport_fit_releases_its_temporary_driver(clock_case):
    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    entered = anyio.Event()

    async def apply(_view, _command):
        entered.set()
        await anyio.sleep_forever()

    stream.runtime.perform.side_effect = apply
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "resize", "width": 640, "height": 900})
    ]
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(run, case)
        await entered.wait()
        tasks.cancel_scope.cancel()
    assert clock.driver.closed == 1
    assert clock.touches == [] and case.closed == [True]


async def test_fit_requires_a_retained_physical_resource_key(clock_case):
    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    case.row.resource_key = None
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "resize", "width": 640, "height": 900}),
        WebSocketDisconnect(),
    ]
    await run(case)
    assert clock.driver is None
    stream.runtime.perform.assert_not_awaited()


@pytest.mark.parametrize("already_held", [False, True])
async def test_fit_reopens_the_current_resource_after_its_driver_claim_before_resizing(
    clock_case, monkeypatch, already_held
):
    case, clock = clock_case
    case.row.kind = case.read.kind = "browser"
    original = stream.runtime.DesktopEnvironmentView(AsyncMock(), 1280, 800)
    selected = stream.runtime.DesktopEnvironmentView(AsyncMock(), 1280, 800)
    attachments = []
    detached = []

    @asynccontextmanager
    async def attach(resource, _resolved):
        view = selected if resource.daemon_url.endswith("selected") else original
        attachments.append(view)
        try:
            yield view
        finally:
            detached.append(view)

    require = stream.EnvironmentDriver.require

    async def select_after_claim(driver):
        await require(driver)
        case.row.resource_ciphertext = "sealed-selected-target"
        case.resource = case.resource.model_copy(update={"daemon_url": "http://private-selected"})

    monkeypatch.setattr(stream.runtime, "open_view", attach)
    monkeypatch.setattr(stream.EnvironmentDriver, "require", select_after_claim)
    commands = [json.dumps({"type": "take_over"})] if already_held else []
    commands += [
        json.dumps({"type": "resize", "width": 640, "height": 1500}),
        WebSocketDisconnect(),
    ]
    case.socket.receive_text.side_effect = commands
    await run(case)
    assert len(attachments) >= 2 and attachments[0] is original
    assert all(view is selected for view in attachments[1:])
    assert detached == attachments
    assert stream.runtime.perform.await_count == 1
    assert stream.runtime.perform.await_args.args[0] is selected
    assert stream.runtime.perform.await_args.args[1].height == 1500
    assert clock.driver.closed == 1
