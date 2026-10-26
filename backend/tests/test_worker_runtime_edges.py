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
from dataclasses import replace
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
    hooks: dict[str, object] = {"on_pause": AsyncMock(), "on_ended": AsyncMock()}
    return Worker(
        settings=settings,
        executors={Pool.SYSTEM: InProcessExecutor({}, concurrency=1)},
        tasks={},
        sessions=sessions,
        **(hooks | overrides),  # ty: ignore[invalid-argument-type]
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


@pytest.mark.parametrize(
    "outages,cap,expected",
    [
        (1, 30.0, 1.0),
        (5, 30.0, 16.0),
        (6, 30.0, 30.0),
        (1101, 30.0, 30.0),
        (1101, 3000.0, 3000.0),
        (1101, 0.5, 0.5),
        (1101, 0.0, 0.0),
    ],
)
def test_outage_backoff_caps_the_exponent_before_it_can_overflow(
    monkeypatch: pytest.MonkeyPatch, outages: int, cap: float, expected: float
) -> None:
    sessions, _ = _sessions()
    worker = _worker(sessions)
    worker.settings = replace(worker.settings, outage_cap=cap)
    monkeypatch.setattr(runtime.random, "uniform", lambda _low, _high: 0.75)

    assert worker._outage_pause(outages) == expected * 0.75


async def test_upkeep_survives_more_than_1100_database_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, _ = _sessions()
    worker = _worker(sessions)
    work = AsyncMock(side_effect=OSError("database offline"))
    pauses: list[float] = []

    async def pause(seconds: float) -> None:
        pauses.append(seconds)
        if len(pauses) == 1101:
            raise asyncio.CancelledError

    monkeypatch.setattr(runtime.asyncio, "sleep", pause)
    monkeypatch.setattr(runtime, "logger", MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await worker._every("heartbeat", 15.0, work)

    assert work.await_count == 1101
    assert all(0.0 < delay <= worker.settings.outage_cap for delay in pauses)


_ANSWERS: dict[object, dict[str, object]] = {
    runtime.job_repo: {
        "complete": True,
        "bury": True,
        "fail": FailOutcome.RETRYING,
        "release": "queued",
        "unclaim": True,
        "claim": None,
        "extend_leases": None,
        "rescue_expired": [],
        "unsettled_ends": [],
        "claim_settlement": True,
        "mark_settled": None,
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


async def test_the_heartbeat_renews_only_the_jobs_still_owed(repos: MagicMock) -> None:
    """A job whose settlement was abandoned is no longer renewed, so its lease runs
    out and the rescuer writes it off - renewed for the life of the process, it
    stayed `running` until a restart (Codex, #2248)."""
    held, abandoned = _job(), _job()
    worker = _worker(_sessions(failures=2)[0])
    executor = worker.executors[Pool.SYSTEM]
    worker._held.update({held.id, abandoned.id})

    await worker._execute(executor, await executor.acquire(), abandoned)
    worker.sessions = _sessions()[0]
    await worker._beat()

    assert repos.extend_leases.await_args.kwargs["job_ids"] == [held.id]


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

    await worker._count_death(MagicMock(), "test-ok", None)

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


async def test_a_job_claimed_as_the_stop_arrived_goes_back_unstarted(repos: MagicMock) -> None:
    """Codex on #2248: the claim's await outlived the SIGTERM, and the job ran anyway,
    to be cancelled thirty seconds later with its one attempt spent."""
    sessions, _opened = _sessions()
    worker = _worker(sessions)
    stop = asyncio.Event()
    job = _job()

    async def claim_while_stopping(*_: object, **__: object) -> ClaimedJob:
        stop.set()
        return job

    repos.claim.side_effect = claim_while_stopping

    await asyncio.wait_for(worker._dispatch(Pool.SYSTEM, stop), timeout=5)

    repos.unclaim.assert_awaited_once()
    assert repos.unclaim.await_args.kwargs == {"fence": job.attempts}
    assert worker._running == set()


async def test_an_unclaim_the_database_refuses_is_left_to_the_rescuer(
    repos: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    sessions, _opened = _sessions(failures=1)

    with caplog.at_level(logging.WARNING, logger="app.worker.runtime"):
        await _worker(sessions)._unclaim(_job())

    assert [record.message for record in caplog.records] == ["background_unclaim_failed"]


@pytest.mark.parametrize(
    ("outcome", "fail", "why"),
    [
        (Failed("boom"), FailOutcome.DEAD, "boom"),
        (Failed("boom"), FailOutcome.SUPERSEDED, "boom"),
        (Died("killed by SIGKILL"), FailOutcome.DEAD, "killed by SIGKILL"),
        (Failed("bad payload", permanent=True), None, "bad payload"),
    ],
    ids=["failed-last", "superseded", "died-last", "buried"],
)
async def test_a_job_that_ended_for_good_hands_its_ending_on_after_the_commit(
    repos: MagicMock, outcome: Outcome, fail: FailOutcome | None, why: str
) -> None:
    """Codex on #2248: a dead child cannot settle the document it was parsing."""
    if fail is not None:
        repos.fail.return_value = fail
    sessions, _opened = _sessions()
    worker = _worker(sessions)
    job = _job()

    await worker._settle(job, outcome)

    worker.on_ended.assert_awaited_once_with(job.kind, job.payload, why)  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    "outcome", [Succeeded(), Failed("boom"), Died("killed")], ids=["ok", "retry", "died-retry"]
)
async def test_a_job_with_attempts_to_come_hands_nothing_on(
    repos: MagicMock, outcome: Outcome
) -> None:
    sessions, _opened = _sessions()
    worker = _worker(sessions)

    await worker._settle(_job(), outcome)

    worker.on_ended.assert_not_awaited()  # ty: ignore[unresolved-attribute]


async def test_an_ending_that_cannot_be_settled_is_logged_not_raised(
    repos: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    repos.fail.return_value = FailOutcome.DEAD
    sessions, _opened = _sessions()
    worker = _worker(sessions, on_ended=AsyncMock(side_effect=RuntimeError("db gone")))

    with caplog.at_level(logging.ERROR, logger="app.worker.runtime"):
        await worker._settle(_job(), Failed("boom"))

    assert [record.message for record in caplog.records] == ["background_job_end_unsettled"]


@pytest.mark.parametrize(
    ("status", "ended"), [("dead", True), ("cancelled", True), ("queued", False)]
)
async def test_a_job_released_at_shutdown_hands_its_ending_on_only_when_it_ended(
    repos: MagicMock, status: str, ended: bool
) -> None:
    repos.release.return_value = status
    sessions, _opened = _sessions()
    worker = _worker(sessions)

    await worker._give_back(_job())

    assert worker.on_ended.await_count == int(ended)  # ty: ignore[unresolved-attribute]


async def test_the_rescuer_settles_every_end_still_owed_and_records_it(
    repos: MagicMock,
) -> None:
    """Rescued or not: an end whose settler never ran to the end - the database was
    down, say - is run again, and stamped settled once it does (Codex, #2248)."""
    from app.repositories.background_job import UnsettledEnd

    owed = UnsettledEnd(id=uuid4(), kind="ingest-document", payload={"a": 1}, why="worker lost")
    repos.unsettled_ends.return_value = [owed]
    sessions, _opened = _sessions()
    worker = _worker(sessions)

    await worker._rescue()

    worker.on_ended.assert_awaited_once_with(  # ty: ignore[unresolved-attribute]
        "ingest-document", {"a": 1}, "worker lost"
    )
    repos.mark_settled.assert_awaited_once()
    assert repos.mark_settled.await_args.args[1] == owed.id


async def test_a_settler_that_fails_leaves_the_end_owed(repos: MagicMock) -> None:
    sessions, _opened = _sessions()
    worker = _worker(sessions, on_ended=AsyncMock(side_effect=RuntimeError("down")))

    await worker._ended(uuid4(), "ingest-document", {}, "dead")

    repos.mark_settled.assert_not_awaited()


async def test_an_end_another_caller_holds_or_already_settled_is_not_settled_again(
    repos: MagicMock,
) -> None:
    """#2334: the worker that saw the death and a rescuer pass both reach the end."""
    repos.claim_settlement.return_value = False
    sessions, _opened = _sessions()
    worker = _worker(sessions)

    await worker._ended(uuid4(), "ingest-document", {}, "dead")

    worker.on_ended.assert_not_awaited()  # ty: ignore[unresolved-attribute]
    repos.mark_settled.assert_not_awaited()


async def test_a_rescued_death_counts_in_its_organizations_scope(repos: MagicMock) -> None:
    from app.repositories.background_job import RescuedJob

    organization = uuid4()
    repos.rescue_expired.return_value = [
        RescuedJob(id=uuid4(), kind="ingest-document", status="dead", organization_id=organization)
    ]
    sessions, _opened = _sessions()

    await _worker(sessions)._rescue()

    assert repos.record_death.await_args.args[1:] == ("ingest-document", organization)


async def test_executor_whose_start_fails_is_still_closed(repos: MagicMock) -> None:
    sessions, _ = _sessions()
    executor = MagicMock(
        start=AsyncMock(side_effect=RuntimeError("partial startup")), close=AsyncMock()
    )
    worker = Worker(
        settings=WorkerSettings(worker_id="test-worker", hostname="test"),
        sessions=sessions,
        tasks={},
        executors={Pool.INGEST: executor},
        on_pause=AsyncMock(),
        on_ended=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="partial startup"):
        await worker.run(asyncio.Event())
    executor.close.assert_awaited_once()
