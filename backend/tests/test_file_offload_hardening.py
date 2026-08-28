"""The request-path file offload is bounded and cancellation-safe (#1108).

#25 moved the blocking upload write, read and parse off the request loop with
`asyncio.to_thread`, which freed the loop but left two gaps on the shared default
executor: a cancelled write orphaned its file, and a burst of parses could occupy
every worker the loop also hands `bcrypt` and DNS. Both are closed by routing the
work through a dedicated bounded pool and making the write clean up after itself
when cancelled.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from app.core.blocking import run_blocking, write_bytes_cancel_safe
from app.services.file_storage import LocalFileStorage
from app.services.file_upload import FileUploadService

pytestmark = pytest.mark.anyio


async def test_run_blocking_runs_on_the_dedicated_file_pool() -> None:
    """Not the loop's default executor, which `bcrypt` and DNS share."""
    name = await run_blocking(lambda: threading.current_thread().name)
    assert name.startswith("file-io")


async def test_an_uncancelled_write_leaves_the_file(tmp_path: Path) -> None:
    target = tmp_path / "keep.bin"
    await write_bytes_cancel_safe(target, b"payload")
    assert target.read_bytes() == b"payload"


async def test_a_cancelled_save_removes_the_file_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crux: an executor cannot interrupt a running `write_bytes`, so a save
    cancelled mid-write must wait the write out and delete the file it left,
    because the caller never received a path to clean up itself."""
    storage = LocalFileStorage(base_dir=tmp_path)
    entered = threading.Event()
    allow = threading.Event()
    original_write = Path.write_bytes

    def slow_write(self: Path, data: bytes) -> int:
        entered.set()
        allow.wait(5)
        return original_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", slow_write)

    task = asyncio.create_task(storage.save("user", "doc.txt", b"payload"))
    # `entered` is a threading.Event set from the write thread - it cannot be an
    # asyncio.Event awaited here, so this polls it.
    while not entered.is_set():  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    task.cancel()
    allow.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == []


async def test_a_save_cancelled_before_it_runs_creates_nothing(tmp_path: Path) -> None:
    """Cancelling before the loop steps the coroutine raises at its first line,
    so no write is ever submitted and there is nothing to clean up."""
    storage = LocalFileStorage(base_dir=tmp_path)
    task = asyncio.create_task(storage.save("user", "doc.txt", b"payload"))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


async def test_an_uncancelled_delete_removes_the_file(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    stored = await storage.save("user", "doc.txt", b"payload")
    await storage.delete(stored)
    assert not (tmp_path / stored).exists()


async def test_deleting_a_missing_path_through_the_helper_is_a_no_op(tmp_path: Path) -> None:
    """`unlink(missing_ok=True)` makes concurrent deletes of one path idempotent -
    a path another cleanup already removed must not raise (#1294)."""
    storage = LocalFileStorage(base_dir=tmp_path)
    await storage.delete("user/never-written.bin")


async def test_a_cancelled_delete_finishes_the_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An executor cannot interrupt a running unlink, so a delete cancelled
    mid-unlink must wait it out - returning while it ran on in the background
    would let the caller's follow-up be skipped with the old file already gone
    (#1294)."""
    storage = LocalFileStorage(base_dir=tmp_path)
    stored = await storage.save("user", "doc.txt", b"payload")
    entered = threading.Event()
    allow = threading.Event()
    original_unlink = Path.unlink

    def slow_unlink(self: Path, *args: object, **kwargs: object) -> None:
        entered.set()
        allow.wait(5)
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", slow_unlink)

    task = asyncio.create_task(storage.delete(stored))
    while not entered.is_set():  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    task.cancel()
    allow.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not (tmp_path / stored).exists()


async def test_a_second_cancellation_does_not_detach_the_delete_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancellation arriving while the drain waits the unlink out must not carry
    the caller off and leave it detached; cancelling twice still finishes the
    unlink (#1294)."""
    storage = LocalFileStorage(base_dir=tmp_path)
    stored = await storage.save("user", "doc.txt", b"payload")
    entered = threading.Event()
    allow = threading.Event()
    original_unlink = Path.unlink

    def slow_unlink(self: Path, *args: object, **kwargs: object) -> None:
        entered.set()
        allow.wait(5)
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", slow_unlink)

    task = asyncio.create_task(storage.delete(stored))
    while not entered.is_set():  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    allow.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not (tmp_path / stored).exists()


async def test_parse_content_still_extracts_text_through_the_pool() -> None:
    """The parse wiring moved to `run_blocking`; the extraction is unchanged."""
    service = FileUploadService(db=None)  # type: ignore[arg-type]  # parse touches no db
    assert await service.parse_content(b"hello\nworld", "text") == "hello\nworld"


def test_a_non_positive_pool_size_is_refused_at_startup() -> None:
    """`ThreadPoolExecutor` raises on `max_workers <= 0`, but on the first file
    op rather than at boot; the setting is constrained so the config is refused
    instead (#1108)."""
    import pydantic

    from app.core.config import Settings

    with pytest.raises(pydantic.ValidationError):
        Settings(FILE_IO_MAX_WORKERS=0)


@pytest.mark.anyio
async def test_a_burst_does_not_queue_its_buffers_in_the_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admission gate is the backpressure (#1108). The pool already bounds
    how many jobs *run*, but its pending queue is unbounded - so the gate's job
    is to keep the surplus out of that queue (where each waiting callable pins
    its buffer). With the gate sized to 1, two extra jobs wait in their own
    frames and the executor's work queue stays empty; without it they would sit
    in that queue. Asserted on the executor's own queue, which is where the
    unbounded memory growth would show."""
    import weakref as _weakref

    from app.core import blocking
    from app.core.config import settings

    monkeypatch.setattr(settings, "FILE_IO_MAX_WORKERS", 1)
    monkeypatch.setattr(blocking, "_executor", None)
    monkeypatch.setattr(blocking, "_limiters", _weakref.WeakKeyDictionary())

    release = threading.Event()

    def _job() -> None:
        release.wait(5)

    tasks = [asyncio.create_task(run_blocking(_job)) for _ in range(3)]
    await asyncio.sleep(0.3)
    queued = blocking._pool()._work_queue.qsize()
    release.set()
    await asyncio.gather(*tasks)

    # One job holds the single pool thread; the other two are parked on the gate,
    # not sitting in the executor queue with their work items.
    assert queued == 0

    # And the gate is one shared instance per loop (the cached path).
    assert blocking._limiter() is blocking._limiter()


async def test_a_cancelled_call_holds_its_slot_until_the_thread_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An executor cannot interrupt a running job, so releasing the admission
    slot when the caller unwinds hands it to a new submission while the old
    worker is still occupied - and a wave of cancellations then admits
    arbitrarily many jobs into the pool's unbounded pending queue, which is the
    growth the gate exists to prevent. With the gate sized to 1 and its single
    job cancelled but still running, a second caller must wait rather than
    queue. Against a release-on-unwind gate the second job is submitted at once
    and sits in that queue."""
    import weakref as _weakref

    from app.core import blocking
    from app.core.config import settings

    monkeypatch.setattr(settings, "FILE_IO_MAX_WORKERS", 1)
    monkeypatch.setattr(blocking, "_executor", None)
    monkeypatch.setattr(blocking, "_limiters", _weakref.WeakKeyDictionary())

    entered = threading.Event()
    release = threading.Event()

    def _held() -> None:
        entered.set()
        release.wait(5)

    first = asyncio.create_task(run_blocking(_held))
    while not entered.is_set():  # noqa: ASYNC110
        await asyncio.sleep(0.01)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(run_blocking(lambda: "done"))
    await asyncio.sleep(0.2)

    # The worker is still occupied by the cancelled job, so the slot is not back
    # and nothing has been handed to the executor behind it.
    assert not second.done()
    assert blocking._pool()._work_queue.qsize() == 0

    release.set()
    assert await second == "done"


async def test_a_second_cancellation_does_not_detach_the_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cleanup is what makes a cancelled write safe, so a cancellation
    arriving *while it runs* must not carry the caller out and leave it
    detached - the loop then cancels it with everything else and the orphan the
    function exists to prevent survives. Cancelling twice must still remove the
    file."""
    target = tmp_path / "orphan.bin"
    entered = threading.Event()
    allow = threading.Event()
    original_write = Path.write_bytes

    def slow_write(self: Path, data: bytes) -> int:
        entered.set()
        allow.wait(5)
        return original_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", slow_write)

    task = asyncio.create_task(write_bytes_cancel_safe(target, b"payload"))
    while not entered.is_set():  # noqa: ASYNC110
        await asyncio.sleep(0.01)

    task.cancel()
    await asyncio.sleep(0)
    # The second cancellation lands while `_discard` is waiting the write out.
    task.cancel()
    allow.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not target.exists()


async def test_a_submission_that_is_refused_gives_the_slot_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ThreadPoolExecutor.submit` raises once the pool is shut down, which
    happens at interpreter exit while work may still be arriving. The slot is
    taken before the submission, so a refusal has to hand it back - otherwise
    the gate loses a permit permanently and the pool narrows by one for the life
    of the process."""
    import weakref as _weakref
    from concurrent.futures import ThreadPoolExecutor

    from app.core import blocking
    from app.core.config import settings

    monkeypatch.setattr(settings, "FILE_IO_MAX_WORKERS", 1)
    monkeypatch.setattr(blocking, "_executor", None)
    monkeypatch.setattr(blocking, "_limiters", _weakref.WeakKeyDictionary())

    closed = ThreadPoolExecutor(max_workers=1)
    closed.shutdown()
    monkeypatch.setattr(blocking, "_pool", lambda: closed)

    with pytest.raises(RuntimeError):
        await run_blocking(lambda: "never")

    # The permit is back, so the gate still admits its one caller.
    assert not blocking._limiter().locked()
