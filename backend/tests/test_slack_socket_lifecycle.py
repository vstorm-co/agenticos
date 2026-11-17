"""A Slack Socket Mode session closes its client on every exit.

`_run_socket_mode` opens an aiohttp `SocketModeClient` - its own
`ClientSession`, a WSS connection and a registered listener - and then blocks in
`heartbeat` for the life of the connection. Two exits used to orphan all three:
`stop_polling` cancels the task and `CancelledError` unwinds out of `heartbeat`,
and a crash the supervisor catches re-enters this coroutine every five seconds
without disconnecting the previous client. The `try/finally` around the session
is what makes each of those release the client (#33).
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.channels import connection_state
from app.services.channels.slack import SlackAdapter

pytestmark = pytest.mark.anyio


class _FakeSocketClient:
    """Records `connect`/`close` so a test can prove the session cleaned up."""

    def __init__(self, **_: object) -> None:
        self.socket_mode_request_listeners: list[Any] = []
        self.connect = AsyncMock()
        self.close = AsyncMock()


def _capture_clients(monkeypatch: pytest.MonkeyPatch) -> list[_FakeSocketClient]:
    created: list[_FakeSocketClient] = []

    class _Recording(_FakeSocketClient):
        def __init__(self, **kw: object) -> None:
            super().__init__(**kw)
            created.append(self)

    monkeypatch.setattr("slack_sdk.socket_mode.aiohttp.SocketModeClient", _Recording)
    monkeypatch.setattr(connection_state, "record_up", AsyncMock())
    return created


def _adapter_with_token() -> SlackAdapter:
    adapter = SlackAdapter()
    adapter._app_tokens["bot"] = "xapp-token"
    return adapter


async def test_a_cancelled_socket_session_closes_its_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _capture_clients(monkeypatch)
    reached = asyncio.Event()
    release = asyncio.Event()

    async def blocking_heartbeat(_bot: str) -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(connection_state, "heartbeat", blocking_heartbeat)

    task = asyncio.create_task(_adapter_with_token()._run_socket_mode("bot", "xoxb-token"))
    await reached.wait()  # the client is connected and the session is blocking

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert created[0].connect.await_count == 1
    assert created[0].close.await_count == 1


async def test_a_crashing_socket_session_closes_its_client_before_reraising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The crash-reconnect leak: the supervisor's `except` re-enters this
    coroutine, so the session it caught must have released its client first."""
    created = _capture_clients(monkeypatch)

    async def crashing_heartbeat(_bot: str) -> None:
        raise RuntimeError("wss dropped")

    monkeypatch.setattr(connection_state, "heartbeat", crashing_heartbeat)

    with pytest.raises(RuntimeError, match="wss dropped"):
        await _adapter_with_token()._run_socket_mode("bot", "xoxb-token")

    assert created[0].close.await_count == 1


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize(
    "kind", ["events_api", "slash_commands", "message_action", "block_actions"]
)
async def test_acknowledgement_follows_admission_but_precedes_prompt_decisions(
    monkeypatch, failed, kind
):
    from types import SimpleNamespace

    created = _capture_clients(monkeypatch)
    adapter = _adapter_with_token()
    admitted = []

    async def handle(_payload, _bot):
        if failed:
            raise RuntimeError("database unavailable")
        admitted.append(True)

    async def heartbeat(_bot):
        socket = created[0]

        async def ack(_response):
            assert admitted == ([] if kind == "block_actions" else [True])

        socket.send_socket_mode_response = AsyncMock(side_effect=ack)
        handler = socket.socket_mode_request_listeners[0]
        request = SimpleNamespace(
            type="interactive" if kind in {"message_action", "block_actions"} else kind,
            payload={"type": kind}
            if kind in {"message_action", "block_actions"}
            else {"event": {}},
            envelope_id="event-1",
        )
        if failed:
            with pytest.raises(RuntimeError, match="database unavailable"):
                await handler(socket, request)
            if kind == "block_actions":
                socket.send_socket_mode_response.assert_awaited_once()
            else:
                socket.send_socket_mode_response.assert_not_awaited()
        else:
            await handler(socket, request)
            socket.send_socket_mode_response.assert_awaited_once()

    async def interaction(_kind, payload, bot_id):
        await handle(payload, bot_id)

    monkeypatch.setattr(adapter, "_handle_event", handle)
    monkeypatch.setattr(adapter, "_handle_interaction", interaction)
    monkeypatch.setattr(connection_state, "heartbeat", heartbeat)
    await adapter._run_socket_mode("bot", "xoxb-token")
