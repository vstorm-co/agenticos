"""TLS DSNs and indefinite retry belong to the optional wake-up connection."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qsl, urlsplit

import asyncpg
import pytest
from asyncpg.connect_utils import _parse_connect_dsn_and_args

from app.worker import listener as module

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "mode", ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
)
def test_the_listener_uses_libpq_sslmode_without_changing_credentials(mode: str) -> None:
    source = f"postgresql+asyncpg://user:p%40ss%2Fword@db.example:5432/app?ssl={mode}&application_name=worker"
    converted = module.asyncpg_dsn(source)
    parts = urlsplit(converted)
    assert parts.scheme == "postgresql"
    assert parts.netloc == "user:p%40ss%2Fword@db.example:5432"
    assert parse_qsl(parts.query) == [("sslmode", mode), ("application_name", "worker")]


def test_a_dsn_without_tls_settings_keeps_its_other_options() -> None:
    assert (
        module.asyncpg_dsn("postgresql+asyncpg://user@localhost/app")
        == "postgresql://user@localhost/app"
    )
    assert module.asyncpg_dsn("postgresql://user@localhost/app?sslmode=require") == (
        "postgresql://user@localhost/app?sslmode=require"
    )


def test_asyncpg_consumes_tls_instead_of_forwarding_it_to_postgres() -> None:
    _, params = _parse_connect_dsn_and_args(
        dsn=module.asyncpg_dsn(
            "postgresql+asyncpg://user:password@db.example/app?ssl=require&application_name=worker"
        ),
        host=None,
        port=None,
        user=None,
        password=None,
        passfile=None,
        database=None,
        ssl=None,
        service=None,
        servicefile=None,
        direct_tls=None,
        server_settings=None,
        target_session_attrs=None,
        krbsrvname=None,
        gsslib=None,
    )
    assert params.server_settings == {"application_name": "worker"}
    assert params.sslmode.name == "require"


async def test_more_than_1100_failed_connections_still_retry_and_can_be_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect = AsyncMock(side_effect=asyncpg.CannotConnectNowError("offline"))
    pauses: list[float] = []

    async def pause(delay: float) -> None:
        pauses.append(delay)
        if len(pauses) == 1101:
            raise asyncio.CancelledError

    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setattr(module.asyncio, "sleep", pause)
    monkeypatch.setattr(module, "logger", MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await module.listener("postgresql://db/app")(lambda _pool: None)
    assert connect.await_count == 1101
    assert pauses[:6] == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert all(delay == 30.0 for delay in pauses[4:])


async def test_a_successful_connection_resets_reconnect_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = False

    async def close(*, timeout: float) -> None:
        nonlocal closed
        assert timeout == 10.0
        closed = True

    connection = MagicMock(is_closed=lambda: closed, close=AsyncMock(side_effect=close))
    connect = AsyncMock(side_effect=[OSError(), OSError(), connection, OSError()])
    pauses: list[float] = []

    async def pause(delay: float) -> None:
        pauses.append(delay)
        if len(pauses) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setattr(module.asyncio, "sleep", pause)
    monkeypatch.setattr(module, "_serve", AsyncMock())
    monkeypatch.setattr(module, "logger", MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await module.listener("postgresql://db/app")(lambda _pool: None)
    assert pauses == [2.0, 4.0, 2.0]
    connection.close.assert_awaited_once()
    assert closed
    connection.terminate.assert_not_called()


@pytest.mark.parametrize(
    "failure", [ConnectionResetError("lost"), asyncpg.InterfaceError("closed"), TimeoutError()]
)
async def test_losing_the_connection_during_listen_retries_and_closes_it(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    connections = [
        MagicMock(
            is_closed=MagicMock(return_value=False),
            close=AsyncMock(),
            add_listener=AsyncMock(side_effect=failure),
        )
        for _ in range(3)
    ]
    connect = AsyncMock(side_effect=connections)
    pauses: list[float] = []

    async def pause(seconds: float) -> None:
        pauses.append(seconds)
        if len(pauses) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setattr(module.asyncio, "sleep", pause)
    monkeypatch.setattr(module, "logger", MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await module.listener("postgresql://db/app", reconnect_cap=5.0)(lambda _pool: None)

    assert connect.await_count == 3
    assert pauses == [2.0, 4.0, 5.0]
    for connection in connections:
        connection.close.assert_awaited_once()


async def test_a_failed_close_is_logged_and_reconnected_with_a_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock(
        is_closed=MagicMock(return_value=False), close=AsyncMock(side_effect=OSError("lost"))
    )
    connect = AsyncMock(return_value=connection)
    pauses: list[float] = []

    async def pause(seconds: float) -> None:
        pauses.append(seconds)
        if len(pauses) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setattr(module, "_serve", AsyncMock())
    monkeypatch.setattr(module.asyncio, "sleep", pause)
    logger = MagicMock()
    monkeypatch.setattr(module, "logger", logger)
    with pytest.raises(asyncio.CancelledError):
        await module.listener("postgresql://db/app")(lambda _pool: None)

    assert connect.await_count == 2
    assert pauses == [2.0, 2.0]
    assert connection.terminate.call_count == 2
    logger.warning.assert_any_call("background_listener_close_failed", exc_info=True)
    connection.close.assert_awaited_with(timeout=10.0)


async def test_cancelling_a_listener_still_cancels_when_closing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listening = asyncio.Event()
    connection = MagicMock(
        is_closed=MagicMock(return_value=False), close=AsyncMock(side_effect=OSError("lost"))
    )

    async def serve(
        _connection: asyncpg.Connection, _notify: Callable[[str], None], _check_every: float
    ) -> None:
        listening.set()
        await asyncio.Event().wait()

    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setattr(module, "_serve", serve)
    monkeypatch.setattr(module, "logger", MagicMock())
    task = asyncio.create_task(module.listener("postgresql://db/app")(lambda _pool: None))
    await asyncio.wait_for(listening.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    assert connect.await_count == 1
    connection.terminate.assert_called_once()


async def test_a_listener_bug_is_not_treated_as_a_recoverable_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = False

    async def close(*, timeout: float) -> None:
        nonlocal closed
        assert timeout == 10.0
        closed = True

    connection = MagicMock(is_closed=lambda: closed, close=close)
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setattr(module, "_serve", AsyncMock(side_effect=RuntimeError("listener bug")))
    with pytest.raises(RuntimeError, match="listener bug"):
        await module.listener("postgresql://db/app")(lambda _pool: None)

    assert closed
    assert connect.await_count == 1
    connection.terminate.assert_not_called()
