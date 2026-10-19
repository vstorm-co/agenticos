"""The worker's rarer turns, which a live worker against a real queue reaches only by luck (#2219).

`tests/integration/test_worker_runtime.py` drives the whole worker; this pins the
branches between its happy and its fatal paths: a job taken over while it ran,
a settle or a release the database never took, a notification for a pool this
worker does not serve, and the schedule loop. The repositories are replaced
with mocks so each turn can be set up exactly.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories.background_job import ClaimedJob, FailOutcome
from app.worker import runtime
from app.worker.executors import Died, Failed, InProcessExecutor, Outcome, Succeeded
from app.worker.jobs import Pool
from app.worker.runtime import Worker, WorkerSettings

pytestmark = pytest.mark.anyio

Sessions = Callable[[], AbstractAsyncContextManager[MagicMock]]


def _sessions(*, failures: int = 0) -> tuple[Sessions, list[MagicMock]]:
    """A session factory that fails to connect `failures` times, then hands out mocks."""
    opened: list[MagicMock] = []
    remaining = [failures]

    @asynccontextmanager
    async def session() -> AsyncIterator[MagicMock]:
        if remaining[0] > 0:
            remaining[0] -= 1
            raise OSError("connection refused")
        db = MagicMock()
        opened.append(db)
        yield db

    return session, opened


def _worker(sessions: Sessions, **overrides: object) -> Worker:
    settings = WorkerSettings(
        worker_id="w",
        hostname="h",
        heartbeat_every=0.01,
        rescue_every=0.01,
        schedule_every=0.01,
        poll_every=0.01,
        outage_cap=0.001,
        settle_attempts=2,
        health_file=None,
    )
    return Worker(
        settings=settings,
        executors={Pool.SYSTEM: InProcessExecutor({}, concurrency=1)},
        tasks={},
        sessions=sessions,
        on_pause=AsyncMock(),
        **overrides,
    )


def _job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        kind="test-ok",
        payload={},
        attempts=1,
        max_attempts=3,
        organization_id=None,
        schedule_name=None,
    )


_ANSWERS: dict[object, dict[str, object]] = {
    runtime.job_repo: {
        "complete": True,
        "bury": True,
        "fail": FailOutcome.RETRYING,
        "release": True,
        "claim": None,
        "extend_leases": None,
        "rescue_expired": [],
    },
    runtime.kind_repo: {
        "record_survival": None,
        "record_lease_lost": None,
        "record_death": 1,
        "pause": True,
    },
    runtime.worker_repo: {"beat": None, "remove": None, "forget_silent_since": None},
}


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Every repository call the worker makes, as one mock to set up and read."""
    repos = MagicMock()
    for module, answers in _ANSWERS.items():
        for name, answer in answers.items():
            mock = AsyncMock(return_value=answer)
            setattr(repos, name, mock)
            monkeypatch.setattr(module, name, mock)
    return repos


@pytest.mark.parametrize(
    ("outcome", "writer", "lost"),
    [
        (Succeeded(), "complete", False),
        (Failed("boom", permanent=True), "bury", False),
        (Failed("boom"), "fail", FailOutcome.LOST),
        (Died("killed by SIGKILL"), "fail", FailOutcome.LOST),
    ],
)
async def test_a_job_taken_over_while_it_ran_is_counted_as_a_possible_duplicate(
    repos: MagicMock, outcome: Outcome, writer: str, lost: object
) -> None:
    getattr(repos, writer).return_value = lost
    sessions, _opened = _sessions()

    await _worker(sessions)._settle(_job(), outcome)

    repos.record_lease_lost.assert_awaited_once()
    repos.record_survival.assert_not_awaited()
    repos.record_death.assert_not_awaited()


async def test_a_job_ended_for_good_ends_its_kinds_run_of_deaths(repos: MagicMock) -> None:
    sessions, _opened = _sessions()

    await _worker(sessions)._settle(_job(), Failed("no such kind", permanent=True))

    repos.bury.assert_awaited_once()
    repos.record_survival.assert_awaited_once()


async def test_a_settle_the_database_never_takes_is_given_up_after_its_attempts(
    repos: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """The lease then runs out, and the rescuer writes the job off with its attempt counted."""
    sessions, opened = _sessions(failures=2)

    with caplog.at_level(logging.WARNING, logger="app.worker.runtime"):
        await _worker(sessions)._settle(_job(), Succeeded())

    assert opened == []
    assert [record.message for record in caplog.records] == [
        "background_settle_failed",
        "background_settle_failed",
        "background_settle_abandoned",
    ]


async def test_a_settle_lands_once_the_database_is_back(repos: MagicMock) -> None:
    sessions, opened = _sessions(failures=1)

    await _worker(sessions)._settle(_job(), Succeeded())

    assert len(opened) == 1
    repos.complete.assert_awaited_once()


async def test_a_release_or_a_deregister_the_database_refuses_is_logged_not_raised(
    repos: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    sessions, _opened = _sessions(failures=2)
    worker = _worker(sessions)

    with caplog.at_level(logging.WARNING, logger="app.worker.runtime"):
        await worker._give_back(_job())
        await worker._deregister()

    assert [record.message for record in caplog.records] == [
        "background_release_failed",
        "background_worker_deregister_failed",
    ]


async def test_a_kind_already_paused_is_not_announced_again(repos: MagicMock) -> None:
    repos.record_death.return_value = 9
    repos.pause.return_value = False
    sessions, _opened = _sessions()
    worker = _worker(sessions)

    await worker._count_death(MagicMock(), "test-ok")

    worker.on_pause.assert_not_awaited()  # type: ignore[attr-defined]  - an AsyncMock here


def test_a_notification_for_a_pool_this_worker_does_not_serve_wakes_nothing() -> None:
    sessions, _opened = _sessions()
    worker = _worker(sessions)

    worker.wake("ingest")
    worker.wake("not-a-pool")
    worker.wake("system")

    assert worker._wake[Pool.SYSTEM].is_set()


async def test_a_job_whose_bookkeeping_raised_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    sessions, _opened = _sessions()
    worker = _worker(sessions)

    async def unsettled() -> None:
        raise RuntimeError("the settle itself crashed")

    task = asyncio.create_task(unsettled())
    await asyncio.gather(task, return_exceptions=True)
    with caplog.at_level(logging.ERROR, logger="app.worker.runtime"):
        worker._finished(task)

    assert [record.message for record in caplog.records] == ["background_job_unsettled"]


async def test_the_schedule_ticks_on_a_session_of_its_own_while_the_worker_runs(
    repos: MagicMock,
) -> None:
    sessions, opened = _sessions()
    ticked = asyncio.Event()

    async def schedule(db: MagicMock) -> None:
        assert db in opened
        ticked.set()

    worker = _worker(sessions, schedule=schedule)
    stop = asyncio.Event()
    serving = asyncio.create_task(worker.run(stop))
    await asyncio.wait_for(ticked.wait(), timeout=5)
    stop.set()
    await asyncio.wait_for(serving, timeout=5)

    repos.remove.assert_awaited_once()


async def test_the_rescuer_forgets_workers_silent_for_a_day(repos: MagicMock) -> None:
    sessions, _opened = _sessions()

    await _worker(sessions)._rescue()

    before = repos.forget_silent_since.await_args.kwargs["before"]
    assert datetime.now(UTC) - timedelta(days=1, minutes=1) < before < datetime.now(UTC)
