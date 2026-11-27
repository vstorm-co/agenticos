"""A failed driver release cannot skip closing the independent observer transport."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import WebSocketDisconnect

from app.services import conversation_environment_stream as stream
from tests.test_conversation_environment_stream import case as case
from tests.test_conversation_environment_stream import run

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def failures(error: BaseException) -> list[str]:
    if isinstance(error, BaseExceptionGroup):
        return [message for nested in error.exceptions for message in failures(nested)]
    return [str(error)]


@pytest.mark.parametrize("view_fails", [False, True])
async def test_driver_release_failure_still_closes_observer_and_keeps_both_errors(
    case, monkeypatch, view_fails
):
    driver = AsyncMock()
    driver.close.side_effect = OSError("Driver release DB failed")
    monkeypatch.setattr(stream, "EnvironmentDriver", MagicMock(return_value=driver))
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "take_over"}),
        WebSocketDisconnect(),
    ]

    @asynccontextmanager
    async def opened(resource, resolved):
        assert resource is case.resource and resolved is case.resolved
        try:
            yield stream.runtime.DesktopEnvironmentView(AsyncMock(), 1280, 800)
        finally:
            case.closed.append(True)
            if view_fails:
                raise RuntimeError("Observer transport close failed")

    monkeypatch.setattr(stream.runtime, "open_view", opened)
    with pytest.raises(Exception) as caught:
        await run(case)
    assert case.closed == [True]
    messages = failures(caught.value)
    assert "Driver release DB failed" in messages
    assert ("Observer transport close failed" in messages) is view_fails
    driver.close.assert_awaited_once()


async def test_disconnect_while_sending_initial_state_normally_detaches_open_view(case):
    case.socket.send_text.side_effect = WebSocketDisconnect()
    await run(case)
    assert case.closed == [True]
    case.socket.close.assert_not_awaited()
    stream.runtime.perform.assert_not_awaited()


async def test_repeated_control_requests_and_release_without_lease_are_safe(case, monkeypatch):
    driver = AsyncMock()
    monkeypatch.setattr(stream, "EnvironmentDriver", MagicMock(return_value=driver))
    case.socket.receive_text.side_effect = [
        json.dumps({"type": command})
        for command in ("take_over", "take_over", "give_back", "give_back")
    ] + [WebSocketDisconnect()]
    await run(case)
    driver.acquire.assert_awaited_once()
    driver.close.assert_awaited_once()
    stream.runtime.perform.assert_not_awaited()
    assert case.closed == [True]


@pytest.mark.parametrize("missing_key", [False, True])
async def test_unavailable_or_contended_physical_driver_never_receives_input(
    case, monkeypatch, missing_key
):
    from app.core.exceptions import ConflictError

    driver = AsyncMock()
    driver.acquire.side_effect = ConflictError(message="Another run controls this environment")
    monkeypatch.setattr(stream, "EnvironmentDriver", MagicMock(return_value=driver))
    if missing_key:
        case.row.resource_key = None
    case.socket.receive_text.side_effect = [
        json.dumps({"type": "take_over"}),
        WebSocketDisconnect(),
    ]
    await run(case)
    if missing_key:
        driver.acquire.assert_not_awaited()
    else:
        driver.close.assert_awaited_once()
    stream.runtime.perform.assert_not_awaited()
    assert case.closed == [True]


async def test_revoked_socket_already_disconnected_is_not_closed_again(case):
    import anyio
    from starlette.websockets import WebSocketState

    from app.core.exceptions import AuthorizationError

    case.socket.application_state = case.socket.client_state = WebSocketState.DISCONNECTED
    stream.current_actor.side_effect = [case.ctx, AuthorizationError(message="Access revoked")]

    async def receive():
        await anyio.sleep_forever()

    case.socket.receive_text.side_effect = receive
    await run(case)
    case.socket.close.assert_not_awaited()
    assert case.closed == [True]


async def test_initial_authority_refusal_does_not_close_an_already_disconnected_socket(case):
    from starlette.websockets import WebSocketState

    from app.core.exceptions import NotFoundError

    case.socket.application_state = WebSocketState.DISCONNECTED
    stream.ConversationEnvironmentService.live.side_effect = NotFoundError(
        message="Environment ended"
    )
    await run(case)
    case.socket.close.assert_not_awaited()
    assert case.closed == []
