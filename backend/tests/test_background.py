"""Fire-and-forget work that does not disappear, and a shutdown that waits for it.

Both failure modes this module exists to prevent are silent. A task the event
loop holds only weakly can be collected mid-flight, and an exception inside a
discarded task is never retrieved — in either case the work simply stops and
nothing anywhere says so. The tests below are therefore about references and
log lines rather than return values.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.core import background

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def no_leftovers():
    """Module state, so a task from one test must not be drained by the next."""
    background._running.clear()
    yield
    background._running.clear()


class TestKeepingWorkAlive:
    async def test_a_spawned_task_is_held_until_it_finishes(self) -> None:
        """The reason this module exists: the loop's own reference is weak."""
        started = asyncio.Event()
        release = asyncio.Event()

        async def work() -> None:
            started.set()
            await release.wait()

        task = background.spawn(work(), name="slow-thing")
        await started.wait()

        assert task in background._running

        release.set()
        await task
        assert task not in background._running

    async def test_the_task_carries_the_name_it_was_given(self) -> None:
        """That name is the only context a failure will ever carry."""

        async def work() -> None:
            return None

        task = background.spawn(work(), name="ingest-document-7")
        await task

        assert task.get_name() == "ingest-document-7"


class TestWhatHappensWhenBackgroundWorkFails:
    async def test_a_failure_is_logged_because_there_is_no_caller_to_raise_into(
        self, caplog
    ) -> None:
        async def work() -> None:
            raise RuntimeError("the parser fell over")

        with caplog.at_level(logging.ERROR, logger=background.__name__):
            task = background.spawn(work(), name="ingest-document-7")
            with pytest.raises(RuntimeError):
                await task
            await asyncio.sleep(0)

        assert "ingest-document-7" in caplog.text
        assert "the parser fell over" in caplog.text

    async def test_a_cancelled_task_is_not_reported_as_a_failure(self, caplog) -> None:
        """Cancellation is what shutdown does on purpose; a stack trace for it is noise."""
        release = asyncio.Event()

        async def work() -> None:
            await release.wait()

        with caplog.at_level(logging.ERROR, logger=background.__name__):
            task = background.spawn(work(), name="cancelled-thing")
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)

        assert caplog.text == ""
        assert task not in background._running


class TestDrainingOnShutdown:
    async def test_nothing_in_flight_is_nothing_to_wait_for(self) -> None:
        await background.drain()

        assert not background._running

    async def test_work_that_is_nearly_done_is_allowed_to_finish(self) -> None:
        """Otherwise a restart leaves documents stuck in ``processing`` forever."""
        finished: list[str] = []

        async def work() -> None:
            await asyncio.sleep(0)
            finished.append("done")

        background.spawn(work(), name="nearly-done")
        await background.drain(timeout=5.0)

        assert finished == ["done"]

    async def test_work_that_overruns_the_timeout_is_cancelled(self, caplog) -> None:
        """A shutdown that waits forever is a deployment that never restarts."""

        async def work() -> None:
            await asyncio.Event().wait()

        with caplog.at_level(logging.WARNING, logger=background.__name__):
            task = background.spawn(work(), name="never-ends")
            await background.drain(timeout=0.01)

        assert "never-ends" not in caplog.text
        assert "did not finish" in caplog.text
        assert task.cancelling() or task.cancelled()
