"""Fire-and-forget work that does not disappear, and a shutdown that waits for it.

Both failure modes this module exists to prevent are silent. A task the event
loop holds only weakly can be collected mid-flight, and an exception inside a
discarded task is never retrieved - in either case the work simply stops and
nothing anywhere says so. The tests below are therefore about references and
log lines rather than return values.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def test_a_spawned_task_does_not_inherit_the_impersonation_actor(self) -> None:
        """A long-lived task started inside an impersonated request must not stamp
        its own audit entries with that administrator - #943. The reset happens in
        the task's copied context, so the caller's own actor is left intact."""
        import uuid

        from app.core.audit import current_impersonator, set_impersonator

        admin = uuid.uuid4()
        set_impersonator(admin)
        try:
            seen: list[uuid.UUID | None] = []

            async def work() -> None:
                seen.append(current_impersonator())

            await background.spawn(work(), name="channel-poller")

            assert seen == [None]
            assert current_impersonator() == admin
        finally:
            set_impersonator(None)


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


class TestWorkThatMustNotOutrunItsTransaction:
    """#417. A session with no bind is enough: only `Session.info` is in play."""

    async def test_deferred_work_has_not_started_when_it_is_registered(self) -> None:
        """The whole point. `spawn` here would have the loop start it at once."""
        started = asyncio.Event()

        async def work() -> None:
            started.set()

        session = AsyncSession()
        background.spawn_after_commit(session, work(), name="ingest-document-7")
        await asyncio.sleep(0)

        assert not started.is_set()
        assert not background._running

        background.start_deferred(session)
        await asyncio.sleep(0)

        assert started.is_set()

    async def test_a_committed_session_starts_its_work_under_the_name_it_was_given(
        self,
    ) -> None:
        finished: list[str] = []

        async def work(label: str) -> None:
            finished.append(label)

        session = AsyncSession()
        background.spawn_after_commit(session, work("first"), name="first")
        background.spawn_after_commit(session, work("second"), name="second")

        background.start_deferred(session)
        await background.drain(timeout=5.0)

        assert finished == ["first", "second"]

    async def test_starting_a_session_twice_does_not_run_its_work_twice(self) -> None:
        """A retry must not double-index a document, and the queue is the guard."""
        runs: list[None] = []

        async def work() -> None:
            runs.append(None)

        session = AsyncSession()
        background.spawn_after_commit(session, work(), name="ingest-document-7")

        background.start_deferred(session)
        background.start_deferred(session)
        await background.drain(timeout=5.0)

        assert len(runs) == 1

    async def test_one_sessions_work_is_not_started_by_another(self) -> None:
        """The queue hangs off the unit of work, not off this module."""
        started = asyncio.Event()

        async def work() -> None:
            started.set()

        writer = AsyncSession()
        somebody_else = AsyncSession()
        background.spawn_after_commit(writer, work(), name="ingest-document-7")

        background.start_deferred(somebody_else)
        await asyncio.sleep(0)

        assert not started.is_set()

        background.start_deferred(writer)
        await background.drain(timeout=5.0)
        assert started.is_set()

    async def test_work_deferred_by_a_session_that_never_committed_is_dropped(self, caplog) -> None:
        """Running it would only fail further from the cause: its row is gone."""
        started = asyncio.Event()

        async def work() -> None:
            started.set()

        session = AsyncSession()
        background.spawn_after_commit(session, work(), name="ingest-document-7")

        with caplog.at_level(logging.WARNING, logger=background.__name__):
            background.discard_deferred(session)
        await asyncio.sleep(0)

        assert not started.is_set()
        assert not background._running
        assert "ingest-document-7" in caplog.text

    async def test_discarding_a_committed_session_finds_nothing_to_drop(self, caplog) -> None:
        """`_managed_session` discards in a `finally`, so it runs after every commit."""

        async def work() -> None:
            return None

        session = AsyncSession()
        background.spawn_after_commit(session, work(), name="ingest-document-7")
        background.start_deferred(session)

        with caplog.at_level(logging.WARNING, logger=background.__name__):
            background.discard_deferred(session)
        await background.drain(timeout=5.0)

        assert caplog.text == ""


class TestDrainingOnShutdown:
    async def test_nothing_in_flight_is_nothing_to_wait_for(self) -> None:
        await background.drain()

        assert not background._running

    async def test_work_that_is_nearly_done_is_allowed_to_finish(self) -> None:
        """Otherwise a restart leaves documents stuck in `processing` forever."""
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

    async def test_work_spawned_while_draining_is_also_awaited(self) -> None:
        """A draining task can hand off more work - a channel run finishing a turn
        spawns each of its notifications - and a one-shot wait would return with
        the freshly-spawned task still in flight (#1095)."""
        finished: list[str] = []

        async def child() -> None:
            await asyncio.sleep(0)
            finished.append("child")

        async def parent() -> None:
            finished.append("parent")
            background.spawn(child(), name="child")

        background.spawn(parent(), name="parent")
        await background.drain(timeout=5.0)

        assert finished == ["parent", "child"]

    async def test_a_cancelled_task_settles_before_drain_returns(self) -> None:
        """The lifespan disposes Redis and the database the moment drain returns,
        and a cancelled task unwinds through its own finally on those same
        resources; drain must not hand back until it has (#1095)."""
        cleaned = asyncio.Event()

        async def work() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        task = background.spawn(work(), name="holds-redis")
        await background.drain(timeout=0.01)

        assert task.done()
        assert cleaned.is_set()

    async def test_a_stubborn_cancelled_task_does_not_hang_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Awaiting a cancelled task is bounded: cancellation is cooperative, so a
        task that blocks in its cleanup must not hold shutdown open forever (#1095)."""
        monkeypatch.setattr(background, "_CANCEL_GRACE_SECONDS", 0.05)
        release = asyncio.Event()

        async def stubborn() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                await release.wait()

        background.spawn(stubborn(), name="stubborn")
        await asyncio.sleep(0)

        # An unbounded await would hang here; drain must return after the grace.
        await asyncio.wait_for(background.drain(timeout=0.01), timeout=1.0)

        release.set()
        await asyncio.sleep(0)
