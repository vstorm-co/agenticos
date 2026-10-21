"""`ChildPool.run_on` against a stand-in process, for the turns a real child takes at random (#2219).

`tests/test_worker_child_pool.py` kills real children; here the process is a
fake whose pipe and exit can be set exactly, so the timeout, a pipe that broke
under the write, and a cancelled job each take the same path every run.
"""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.executors import ChildPool, Died, Failed, _Child

pytestmark = pytest.mark.anyio


class _Process:
    """A child that never answers until it is killed, and exits with `exit_status`."""

    def __init__(self, *, drain: AsyncMock | None = None, exit_status: int = -9) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self._exit_status = exit_status
        self._exited = asyncio.Event()
        self.stdin = MagicMock(drain=drain or AsyncMock())
        self.stdout = MagicMock(readline=self._silent)

    async def _silent(self) -> bytes:
        await asyncio.Event().wait()
        return b""

    def kill(self) -> None:
        self.returncode = self._exit_status
        self._exited.set()

    async def wait(self) -> int:
        if self.returncode is None and self.stdin.drain.side_effect is not None:
            self.kill()
        await self._exited.wait()
        assert self.returncode is not None
        return self.returncode


def _pool() -> ChildPool:
    return ChildPool(
        size=0, handlers="unused:unused", memory_limit_bytes=None, max_jobs=1, watch_every=0.01
    )


async def test_a_job_past_its_deadline_is_failed_and_its_child_killed() -> None:
    process = _Process()
    with patch("app.worker.executors.resident_bytes", return_value=0):
        outcome = await _pool().run_on(
            _Child(process),
            "test-ok",
            {},
            timeout=timedelta(seconds=0.05),  # type: ignore[arg-type]  - a stand-in process
        )

    assert isinstance(outcome, Failed)
    assert "timed out" in outcome.error
    assert process.returncode == -9


async def test_a_pipe_that_broke_under_the_write_is_the_childs_death() -> None:
    process = _Process(drain=AsyncMock(side_effect=BrokenPipeError()), exit_status=1)

    outcome = await _pool().run_on(_Child(process), "test-ok", {}, timeout=timedelta(seconds=5))  # type: ignore[arg-type]  - a stand-in process

    assert outcome == Died("the child process exited with status 1 without finishing the job")


async def test_a_cancelled_job_takes_its_child_with_it() -> None:
    process = _Process()
    with patch("app.worker.executors.resident_bytes", return_value=0):
        running = asyncio.create_task(
            _pool().run_on(_Child(process), "test-ok", {}, timeout=timedelta(seconds=30))  # type: ignore[arg-type]  - a stand-in process
        )
        await asyncio.sleep(0.05)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    assert process.returncode == -9


async def test_a_closed_pool_replaces_nobody() -> None:
    pool = _pool()
    process = _Process()
    pool._spawn = AsyncMock()  # type: ignore[method-assign]  - must not be reached
    await pool.close()

    await pool._replace(_Child(process))  # type: ignore[arg-type]  - a stand-in process

    pool._spawn.assert_not_awaited()
    assert process.returncode == -9
