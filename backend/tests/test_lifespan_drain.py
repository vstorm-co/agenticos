"""The application lifespan drains in-flight background work before it tears the
process down (#11).

`background.spawn` hands off the slow half of a request - an ingestion, a sync -
to a task the event loop holds only through `background`'s own set. If shutdown
disposes the stores and the session without waiting, that task is cancelled
mid-flight and a document is left in `processing` forever. The regression is
subtle: `drain()` existed and its docstring claimed the lifespan called it, but
nothing did.

Startup's heavy collaborators are stubbed so the lifespan runs in-process; what
is exercised is the real `background.drain()` wiring on the way out.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.core import background

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_leftovers():
    """`background._running` is module state, so a task leaked by another test on
    this worker must not be the one the lifespan's `drain()` waits out - which,
    with the default 30s timeout, would look like a hang rather than a failure."""
    background._running.clear()
    yield
    background._running.clear()


class _FakeRedis:
    async def connect(self) -> None: ...
    async def close(self) -> None: ...


class _FakeAdapter:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self._polling_tasks: dict[str, Any] = {}
        self._socket_tasks: dict[str, Any] = {}

    async def stop_polling(self, _bid: str) -> None: ...


_ADAPTER_CLASSES = {
    "telegram": "TelegramAdapter",
    "slack": "SlackAdapter",
    "mattermost": "MattermostAdapter",
}


def _stub_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    for name in (
        "setup_logfire",
        "load_builtins",
        "instrument_asyncpg",
        "instrument_redis",
        "instrument_httpx",
        "instrument_pydantic_ai",
        "register_adapter",
    ):
        monkeypatch.setattr(main, name, MagicMock())
    monkeypatch.setattr(main, "RedisClient", lambda *a, **k: _FakeRedis())
    monkeypatch.setattr(main, "_start_channel_polling", AsyncMock())
    monkeypatch.setattr(main, "close_db", AsyncMock())
    monkeypatch.setattr(main, "reset_retrieval_service", MagicMock())
    monkeypatch.setattr(main, "EventLoopWatchdog", lambda *a, **k: MagicMock())
    # Warmup raises, so the embedder is None and no PgVectorStore is built - the
    # lifespan swallows it, which is the "RAG unavailable" path and needs no DB.
    monkeypatch.setattr(main, "EmbeddingService", MagicMock(side_effect=RuntimeError("no rag")))
    for channel, cls in _ADAPTER_CLASSES.items():
        monkeypatch.setattr(f"app.services.channels.{channel}.{cls}", _FakeAdapter)


async def test_the_lifespan_waits_for_in_flight_background_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    _stub_startup(monkeypatch)
    finished: list[bool] = []

    async def _slow() -> None:
        await asyncio.sleep(0.05)
        finished.append(True)

    async with main.lifespan(FastAPI()):
        background.spawn(_slow(), name="slow-ingestion")
        assert finished == [], "the handoff must not block startup or serving"

    # Exiting the context runs shutdown, which calls background.drain().
    assert finished == [True], "shutdown cancelled work that was still in flight"
