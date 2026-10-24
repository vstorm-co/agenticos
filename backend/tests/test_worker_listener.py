"""TLS DSNs and indefinite retry belong to the optional wake-up connection."""

import asyncio
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
    connection = MagicMock(is_closed=MagicMock(return_value=False), close=AsyncMock())
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
