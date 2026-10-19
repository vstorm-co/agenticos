"""The ingest pool's child processes, killed for real (#2219).

No database here: these drive `ChildPool` directly and check what it says
about each way a child can end. The hog grows until the memory watchdog stops
it; the suicide sends itself `SIGKILL`, which is what the kernel's
out-of-memory killer does. Each time the parent survives, says why, and has a
fresh child ready for the next job.
"""

import sys
from collections.abc import AsyncGenerator
from datetime import timedelta

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
)

pytestmark = pytest.mark.anyio

HANDLERS = "tests.worker_handlers:handlers"
TIMEOUT = timedelta(seconds=60)


@pytest.fixture
async def pool() -> AsyncGenerator[ChildPool, None]:
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


def test_an_exit_is_described_by_its_signal_or_its_status() -> None:
    assert "SIGKILL" in describe_exit(-9)
    assert describe_exit(-15) == "the child process was killed by SIGTERM"
    assert describe_exit(1) == "the child process exited with status 1 without finishing the job"


def test_the_children_run_on_this_interpreter() -> None:
    assert (
        ChildPool(size=0, handlers=HANDLERS, memory_limit_bytes=None, max_jobs=1).command[0]
        == sys.executable
    )
