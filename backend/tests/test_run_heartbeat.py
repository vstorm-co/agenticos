"""A running run's sign of life (#2301).

The process executing a run stamps it every few seconds, so the stale-run sweep
can tell a dead process from a slow model in minutes. What the stamp writes is
proved against Postgres in `tests/integration/test_stale_run_reaping.py`; these
cover the beat itself - its rhythm, a failed write, and that it stops.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import agent_run_repo
from app.services import run_heartbeat as heartbeat_module
from app.services.run_heartbeat import run_heartbeat

pytestmark = pytest.mark.anyio

RUN = uuid.uuid4()


@pytest.fixture
def beats(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Every stamp, through a session of its own, every few milliseconds."""

    @contextlib.asynccontextmanager
    async def session() -> AsyncGenerator[MagicMock]:
        yield MagicMock()

    stamp = AsyncMock()
    monkeypatch.setattr(heartbeat_module, "get_db_context", session)
    monkeypatch.setattr(agent_run_repo, "beat_run", stamp)
    monkeypatch.setattr(heartbeat_module.settings, "RUN_HEARTBEAT_SECONDS", 0.01)
    return stamp


async def test_a_running_run_is_stamped_every_beat(beats: AsyncMock) -> None:
    async with run_heartbeat(RUN):
        await asyncio.sleep(0.05)

    assert beats.await_count >= 2
    assert {call.kwargs["run_id"] for call in beats.await_args_list} == {RUN}


async def test_a_failed_stamp_is_logged_and_the_next_one_tried(
    beats: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """The run is fine; ending it over a dropped connection would be the sweep's
    mistake made early."""
    beats.side_effect = [ConnectionError("gone"), None, None, None, None, None]

    async with run_heartbeat(RUN):
        await asyncio.sleep(0.05)

    assert beats.await_count >= 2
    assert "run_heartbeat_failed" in caplog.text


async def test_the_beat_stops_with_the_run(beats: AsyncMock) -> None:
    async with run_heartbeat(RUN):
        await asyncio.sleep(0.03)
    stamped = beats.await_count

    await asyncio.sleep(0.05)

    assert beats.await_count == stamped


async def test_the_beat_stops_when_the_run_raises(beats: AsyncMock) -> None:
    """A run that fails or is cancelled still takes its heartbeat with it."""
    with pytest.raises(RuntimeError):
        async with run_heartbeat(RUN):
            raise RuntimeError("model down")
    stamped = beats.await_count

    await asyncio.sleep(0.05)

    assert beats.await_count == stamped
