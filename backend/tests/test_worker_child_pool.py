"""The ingest pool's child processes, killed for real (#2219).

No database here: these drive `ChildPool` directly and check what it says
about each way a child can end. The hog grows until the memory watchdog stops
it; the suicide sends itself `SIGKILL`, which is what the kernel's
out-of-memory killer does. Each time the parent survives, says why, and has a
fresh child ready for the next job.
"""

import asyncio
import logging
import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import JsonValue

from app.worker.executors import (
    ChildPool,
    ChildStartFailed,
    Died,
    Failed,
    Outcome,
    Succeeded,
    _ChildSlot,
    describe_exit,
    resident_bytes,
)

pytestmark = pytest.mark.anyio

HANDLERS = "tests.worker_handlers:handlers"
TIMEOUT = timedelta(seconds=60)


@pytest.fixture
async def pool() -> AsyncGenerator[ChildPool]:
    children = ChildPool(
        size=1,
        handlers=HANDLERS,
        memory_limit_bytes=256 * 2**20,
        max_jobs=3,
        watch_every=0.1,
        respawn_backoff=0.1,
    )
    await children.start()
    try:
        yield children
    finally:
        await children.close()


async def _run(
    pool: ChildPool,
    kind: str,
    payload: dict[str, JsonValue] | None = None,
    *,
    timeout: timedelta = TIMEOUT,
) -> Outcome:
    slot = await pool.acquire()
    try:
        return await slot.run(kind, payload or {}, timeout=timeout)
    finally:
        pool.release(slot)


async def _child_serving(pool: ChildPool) -> object:
    slot = await pool.acquire()
    pool.release(slot)
    assert isinstance(slot, _ChildSlot)
    return slot.child


async def test_a_job_that_succeeds_in_a_child_says_so(pool: ChildPool) -> None:
    assert await _run(pool, "test-ok") == Succeeded()


async def test_a_job_that_answers_in_a_child_sends_the_answer_back(pool: ChildPool) -> None:
    assert await _run(pool, "test-answer", {"text": "forty-two"}) == Succeeded(
        result={"text": "forty-two"}
    )


async def test_a_job_that_raises_reports_the_error_and_the_child_lives_on(pool: ChildPool) -> None:
    outcome = await _run(pool, "test-fail", {"text": "disk full"})
    assert isinstance(outcome, Failed)
    assert outcome.permanent is False
    assert "RuntimeError: disk full" in outcome.error
    assert await _run(pool, "test-ok") == Succeeded()


async def test_a_job_that_outgrows_its_limit_is_stopped_by_the_watchdog(pool: ChildPool) -> None:
    outcome = await _run(pool, "test-hog")
    assert isinstance(outcome, Died)
    assert "memory watchdog" in outcome.reason
    assert "over the limit of 256 MiB" in outcome.reason
    # The parent survived and a new child is serving.
    assert await _run(pool, "test-ok") == Succeeded()


async def test_a_child_killed_by_sigkill_is_reported_as_killed(pool: ChildPool) -> None:
    outcome = await _run(pool, "test-suicide")
    assert isinstance(outcome, Died)
    assert "SIGKILL" in outcome.reason
    assert "out-of-memory" in outcome.reason
    assert await _run(pool, "test-ok") == Succeeded()


async def test_a_child_that_exits_mid_job_is_reported_with_its_status(pool: ChildPool) -> None:
    outcome = await _run(pool, "test-leave")
    assert outcome == Died("the child process exited with status 3 without finishing the job")
    assert await _run(pool, "test-ok") == Succeeded()


async def test_a_job_past_its_timeout_is_stopped_and_failed(pool: ChildPool) -> None:
    outcome = await _run(pool, "test-ok", {"seconds": 30}, timeout=timedelta(seconds=0.5))
    assert isinstance(outcome, Failed)
    assert "timed out" in outcome.error
    assert await _run(pool, "test-ok") == Succeeded()


async def test_an_unknown_kind_and_a_bad_payload_are_permanent_failures(pool: ChildPool) -> None:
    unknown = await _run(pool, "no-such-kind")
    assert isinstance(unknown, Failed)
    assert unknown.permanent is True
    malformed = await _run(pool, "test-ok", {"seconds": "soon"})
    assert isinstance(malformed, Failed)
    assert malformed.permanent is True
    assert "ValidationError" in malformed.error


async def test_a_child_is_recycled_after_its_quota_of_jobs(pool: ChildPool) -> None:
    first = await _child_serving(pool)
    for _ in range(3):
        assert await _run(pool, "test-ok") == Succeeded()
    assert await _child_serving(pool) is not first


async def test_a_child_that_cannot_start_fails_the_pool_start() -> None:
    broken = ChildPool(
        size=1,
        handlers="tests.worker_handlers:no_such_factory",
        memory_limit_bytes=None,
        max_jobs=1,
        start_timeout=60,
    )
    with pytest.raises(ChildStartFailed, match="did not start"):
        await broken.start()
    await broken.close()


async def test_a_job_cancelled_mid_run_stops_its_child_and_a_fresh_one_serves(
    pool: ChildPool,
) -> None:
    """A shutdown cancels the job: its child goes with it, rather than finishing unwatched."""
    first = await _child_serving(pool)
    running = asyncio.create_task(_run(pool, "test-ok", {"seconds": 30}))
    await asyncio.sleep(0.5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert first.process.returncode is not None
    assert await _run(pool, "test-ok") == Succeeded()


async def test_a_child_that_answers_something_unreadable_is_stopped(pool: ChildPool) -> None:
    child = await _child_serving(pool)

    outcome = await pool._answer(child, b"Traceback (most recent call last):\n")

    assert isinstance(outcome, Failed)
    assert "unreadable" in outcome.error
    assert child.process.returncode is not None


async def test_a_replacement_that_fails_to_start_is_tried_again(
    pool: ChildPool, caplog: pytest.LogCaptureFixture
) -> None:
    spawn = pool._spawn
    pool._spawn = AsyncMock(side_effect=[ChildStartFailed("not today"), await spawn()])  # type: ignore[method-assign]  - one failed start, then the real one

    with caplog.at_level(logging.ERROR, logger="app.worker.executors"):
        assert isinstance(await _run(pool, "test-suicide"), Died)
        assert await _run(pool, "test-ok") == Succeeded()

    assert "background_child_start_failed" in [record.message for record in caplog.records]


async def test_a_replacement_the_system_refuses_for_a_moment_is_tried_again(
    pool: ChildPool, caplog: pytest.LogCaptureFixture
) -> None:
    """EMFILE under resource pressure: the slot came back only by retrying, and a
    replacement that gave up left the pool a slot short for good."""
    spawn = pool._spawn
    pool._spawn = AsyncMock(side_effect=[OSError(24, "Too many open files"), await spawn()])  # type: ignore[method-assign]  - one refused fork, then the real one

    with caplog.at_level(logging.ERROR, logger="app.worker.executors"):
        assert isinstance(await _run(pool, "test-suicide"), Died)
        assert await _run(pool, "test-ok") == Succeeded()

    assert "background_child_start_failed" in [record.message for record in caplog.records]


async def test_a_replacement_that_crashes_is_logged(
    pool: ChildPool, caplog: pytest.LogCaptureFixture
) -> None:
    pool._spawn = AsyncMock(side_effect=RuntimeError("no fork for you"))  # type: ignore[method-assign]  - a respawn that crashes outright

    with caplog.at_level(logging.ERROR, logger="app.worker.executors"):
        assert isinstance(await _run(pool, "test-suicide"), Died)
        await asyncio.gather(*pool._respawning, return_exceptions=True)

    assert "background_child_respawn_failed" in [record.message for record in caplog.records]


async def test_a_slot_given_back_after_close_starts_no_replacement() -> None:
    children = ChildPool(size=1, handlers=HANDLERS, memory_limit_bytes=None, max_jobs=1)
    await children.start()
    slot = await children.acquire()
    await children.close()

    children.release(slot)

    assert children._respawning == set()


async def test_a_child_that_never_says_ready_fails_its_start() -> None:
    silent = ChildPool(
        size=1,
        handlers=HANDLERS,
        memory_limit_bytes=None,
        max_jobs=1,
        start_timeout=0.5,
        command=(sys.executable, "-c", "import time; time.sleep(30)"),
    )
    with pytest.raises(ChildStartFailed, match="did not start"):
        await silent.start()
    await silent.close()


def test_a_childs_memory_counts_what_it_started_and_nothing_once_it_is_gone() -> None:
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"]) as started:
        try:
            assert resident_bytes(os.getpid()) > resident_bytes(started.pid) > 0
        finally:
            started.kill()
    assert resident_bytes(gone.pid) == 0


def test_an_exit_is_described_by_its_signal_or_its_status() -> None:
    assert "SIGKILL" in describe_exit(-9)
    assert describe_exit(-15) == "the child process was killed by SIGTERM"
    assert describe_exit(1) == "the child process exited with status 1 without finishing the job"


def test_the_children_run_on_this_interpreter() -> None:
    assert (
        ChildPool(size=0, handlers=HANDLERS, memory_limit_bytes=None, max_jobs=1).command[0]
        == sys.executable
    )


@pytest.mark.parametrize("cancelled", [False, True])
async def test_partial_pool_start_reaps_every_process(
    monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    from app.worker.child import READY

    created: list[asyncio.subprocess.Process] = []
    spawned = asyncio.Event()
    launch = asyncio.create_subprocess_exec
    issued = 0

    async def create(
        *args: str, stdin: int | None = None, stdout: int | None = None
    ) -> asyncio.subprocess.Process:
        nonlocal issued
        marker = READY if issued == 0 else "bad startup"
        issued += 1
        script = (
            "import time; time.sleep(30)"
            if cancelled
            else f"import time; print({marker!r}, flush=True); time.sleep(30)"
        )
        process = await launch(sys.executable, "-c", script, stdin=stdin, stdout=stdout)
        created.append(process)
        if len(created) == 2:
            spawned.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    children = ChildPool(size=2, handlers=HANDLERS, memory_limit_bytes=None, max_jobs=1)
    starting = asyncio.create_task(children.start())
    try:
        await asyncio.wait_for(spawned.wait(), timeout=5)
        if cancelled:
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await starting
        else:
            with pytest.raises(ChildStartFailed):
                await starting
        assert all(process.returncode is not None for process in created)
        assert not children._children
    finally:
        if not starting.done():
            starting.cancel()
        await asyncio.gather(starting, return_exceptions=True)
        await children.close()
        for process in created:
            if process.returncode is None:
                process.kill()
            await process.wait()


@pytest.mark.parametrize("watchdog", [False, True])
async def test_stdin_backpressure_does_not_bypass_job_bounds(watchdog: bool) -> None:
    from app.worker.child import READY

    children = ChildPool(
        size=1,
        handlers=HANDLERS,
        memory_limit_bytes=1 if watchdog else None,
        max_jobs=1,
        watch_every=0.01,
        start_timeout=5,
        command=(
            sys.executable,
            "-c",
            f"import time; print({READY!r}, flush=True); time.sleep(30)",
        ),
    )
    await children.start()
    try:
        async with asyncio.timeout(5):
            outcome = await _run(
                children, "test-ok", {"large": "x" * 2_000_000}, timeout=timedelta(seconds=0.1)
            )
        if watchdog:
            assert isinstance(outcome, Died) and "memory watchdog" in outcome.reason
        else:
            assert isinstance(outcome, Failed) and "timed out" in outcome.error
    finally:
        await children.close()


async def test_a_child_that_closes_stdin_cannot_hold_a_failed_write_open() -> None:
    from app.worker.child import READY

    children = ChildPool(
        size=1,
        handlers=HANDLERS,
        memory_limit_bytes=None,
        max_jobs=1,
        watch_every=0.01,
        command=(
            sys.executable,
            "-c",
            f"import os,time; os.close(0); print({READY!r}, flush=True); time.sleep(30)",
        ),
    )
    await children.start()
    try:
        async with asyncio.timeout(5):
            outcome = await _run(children, "test-ok", {"large": "x" * 2_000_000})
        assert isinstance(outcome, Died)
        assert "closed its connection without exiting" in outcome.reason
    finally:
        await children.close()
