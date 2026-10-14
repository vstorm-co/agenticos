"""The voice socket's admission: the same user and organization auth as /ws/agent (#54)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.routes.v1.voice import voice_websocket
from app.services.voice.session import socket_caller

pytestmark = pytest.mark.anyio


def _socket():
    socket = MagicMock()
    socket.accept = AsyncMock()
    socket.close = AsyncMock()
    socket.state = SimpleNamespace(auth_token="tok", accept_subprotocol="voice")
    return socket


async def test_a_socket_without_a_user_is_closed_4001():
    socket = _socket()
    await voice_websocket(socket, user=None, organization=SimpleNamespace(id=uuid4()))
    socket.close.assert_awaited_once_with(code=4001, reason="Unauthorized")


async def test_a_member_is_a_caller_bound_to_their_organization_and_token():
    org = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=uuid4(), full_name="Ann", is_app_admin=False)
    with patch(
        "app.services.voice.session.member_repo.get",
        AsyncMock(return_value=SimpleNamespace(role="member")),
    ):
        caller = await socket_caller(user, org, auth_token="tok")

    assert caller is not None
    assert caller.ctx.organization_id == org.id and caller.user_id == user.id
    assert caller.auth_token == "tok" and caller.surface == "web" and not caller.anonymous


async def test_a_socket_whose_membership_is_gone_is_closed_4003():
    socket = _socket()
    with patch("app.api.routes.v1.voice.socket_caller", AsyncMock(return_value=None)):
        await voice_websocket(
            socket,
            user=SimpleNamespace(id=uuid4(), full_name=None),
            organization=SimpleNamespace(id=uuid4()),
        )
    socket.close.assert_awaited_once_with(code=4003, reason="Organization access denied")


async def test_an_admitted_socket_is_accepted_with_its_subprotocol_and_run():
    socket = _socket()
    caller = SimpleNamespace()
    with (
        patch("app.api.routes.v1.voice.socket_caller", AsyncMock(return_value=caller)),
        patch("app.api.routes.v1.voice.VoiceCallSession") as session_cls,
    ):
        session_cls.return_value.run = AsyncMock()
        await voice_websocket(
            socket, user=SimpleNamespace(id=uuid4()), organization=SimpleNamespace(id=uuid4())
        )
    socket.accept.assert_awaited_once_with(subprotocol="voice")
    assert session_cls.call_args.args == (socket, caller)
    session_cls.return_value.run.assert_awaited_once()


async def test_a_person_no_longer_a_member_is_no_caller():
    with patch("app.services.voice.session.member_repo.get", AsyncMock(return_value=None)):
        caller = await socket_caller(
            SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4()), auth_token="tok"
        )
    assert caller is None
