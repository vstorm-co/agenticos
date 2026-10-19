"""The minute-scale sweeps the worker runs in its own process (#2213)."""

import asyncio
from typing import Any

import pytest

from app.worker import sweeps
from app.worker.sweeps import Sweep, keep_sweeping, run_sweeps

pytestmark = pytest.mark.anyio


class _Stop(BaseException):
    """Ends a loop that otherwise runs until the worker stops."""


class _Clock:
    """`asyncio.sleep` and `time.monotonic` for a loop: records each wait, stops after `naps`."""

    def __init__(self, naps: int) -> None:
        self.naps = naps
        self.waits: list[float] = []
        self.now = 0.0

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        if len(self.waits) > self.naps:
            raise _Stop
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    async def record(_redis: Any, name: str, _at: Any) -> None:
        seen.append(name)

    monkeypatch.setattr(sweeps.worker_heartbeat, "record", record)
    return seen


def _install(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    monkeypatch.setattr(sweeps.asyncio, "sleep", clock.sleep)
    monkeypatch.setattr(sweeps.time, "monotonic", clock.monotonic)


async def test_a_sweep_ticks_after_its_offset_and_then_every_interval(
    monkeypatch: pytest.MonkeyPatch, recorded: list[str]
) -> None:
    clock = _Clock(naps=3)
    _install(monkeypatch, clock)
    ticks: list[float] = []

    async def tick() -> None:
        ticks.append(clock.now)
        clock.now += 15  # the tick itself took 15 s

    with pytest.raises(_Stop):
        await keep_sweeping(Sweep("agent-triggers-check", 60, tick), None, delay=20)  # type: ignore[arg-type]

    # Waits measured from each tick's start: a 15 s tick leaves 45 s to the next.
    assert clock.waits == [20, 45, 45, 45]
    assert ticks == [20, 80, 140]
    assert recorded == ["agent-triggers-check"] * 3


async def test_a_tick_longer_than_its_interval_runs_the_next_straight_after(
    monkeypatch: pytest.MonkeyPatch, recorded: list[str]
) -> None:
    clock = _Clock(naps=2)
    _install(monkeypatch, clock)

    async def slow() -> None:
        clock.now += 90

    with pytest.raises(_Stop):
        await keep_sweeping(Sweep("portal-poll", 60, slow), None, delay=0)  # type: ignore[arg-type]

    assert clock.waits == [0, 0, 0]


async def test_a_failing_tick_is_logged_and_tried_again_without_a_heartbeat(
    monkeypatch: pytest.MonkeyPatch, recorded: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock(naps=2)
    _install(monkeypatch, clock)
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database went away")

    with pytest.raises(_Stop):
        await keep_sweeping(Sweep("notification-delivery-sweep", 60, flaky), None, delay=0)  # type: ignore[arg-type]

    assert calls == 2
    assert recorded == ["notification-delivery-sweep"]
    assert "sweep_failed" in caplog.text


async def test_a_heartbeat_that_cannot_be_recorded_does_not_stop_the_sweep(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock(naps=2)
    _install(monkeypatch, clock)
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        ticks += 1

    async def redis_down(*_: object) -> None:
        raise ConnectionError("redis")

    monkeypatch.setattr(sweeps.worker_heartbeat, "record", redis_down)

    with pytest.raises(_Stop):
        await keep_sweeping(Sweep("rag-sync-check", 60, tick), None, delay=0)  # type: ignore[arg-type]

    assert ticks == 2
    assert "sweep_heartbeat_unrecorded" in caplog.text


async def test_the_sweeps_start_spread_across_their_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four sweeps waking in the same second was the spike they replaced."""
    started: dict[str, float] = {}

    async def keep(sweep: Sweep, _redis: Any, *, delay: float) -> None:
        started[sweep.name] = delay

    monkeypatch.setattr(sweeps, "keep_sweeping", keep)

    async def nothing() -> None:
        return None

    await run_sweeps([Sweep(name, 60, nothing) for name in "abcd"], None)  # type: ignore[arg-type]

    assert started == {"a": 0, "b": 15, "c": 30, "d": 45}


async def test_cancelling_the_worker_stops_every_sweep() -> None:
    async def nothing() -> None:
        return None

    task = asyncio.create_task(
        run_sweeps([Sweep("a", 60, nothing), Sweep("b", 60, nothing)], None)  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()


class TestTheSyncCheck:
    """`dispatch_due_syncs`: one yes-or-no query, and a flow run only for a yes."""

    @staticmethod
    def _wire(monkeypatch: pytest.MonkeyPatch, *, due: bool) -> Any:
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock

        from app.worker.tasks import rag_tasks

        @asynccontextmanager
        async def session() -> Any:
            yield object()

        monkeypatch.setattr(rag_tasks, "get_worker_db_context", session)
        monkeypatch.setattr(
            rag_tasks.sync_source_repo, "any_due_for_sync", AsyncMock(return_value=due)
        )
        submitted = AsyncMock()
        monkeypatch.setattr("prefect.deployments.run_deployment", submitted)
        return rag_tasks, submitted

    async def test_a_due_source_starts_the_sync_check_without_waiting_for_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rag_tasks, submitted = self._wire(monkeypatch, due=True)

        assert await rag_tasks.dispatch_due_syncs() is True
        submitted.assert_awaited_once_with(name="rag-sync-check/rag-sync-check", timeout=0)

    async def test_nothing_due_starts_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rag_tasks, submitted = self._wire(monkeypatch, due=False)

        assert await rag_tasks.dispatch_due_syncs() is False
        submitted.assert_not_awaited()
