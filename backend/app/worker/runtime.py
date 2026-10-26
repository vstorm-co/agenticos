"""The worker: claims jobs, runs them, and writes down how each ended (#2219).

One process serves one or more pools. For each it holds an executor - jobs on
its own loop, or in child processes for the ingest pool - and claims a job only
once that executor has room for it. Beside the pools run four loops:

* the **heartbeat** extends the lease of every job this worker holds, says the
  worker is alive, and touches the health file the container probe reads;
* the **rescuer** takes back the jobs whose lease ran out - their worker died,
  whoever it was - and writes what happened on each;
* the **scheduler**, when there is one, fires the deployment's due schedules;
* the **listener** wakes a pool the moment a job for it commits, so the poll
  interval is a fallback rather than the latency.

What makes it safe under an out-of-memory kill is not in here but in the
claim (`app.repositories.background_job`): the attempt is spent before the job
runs, so nothing a job does can buy it another. This module's part is to never
hot-loop - a database that is down is retried with a growing pause - and to
count deaths per kind, pausing a kind that keeps killing its workers until the
deployment's owner resumes it.
"""

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil, log2
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import background_job as job_repo
from app.repositories import background_task_kind as kind_repo
from app.repositories import background_worker as worker_repo
from app.repositories.background_job import ClaimedJob, FailOutcome
from app.worker.attempt import Attempt
from app.worker.executors import Died, Executor, Failed, Outcome, Slot, Succeeded
from app.worker.jobs import Pool, TaskKind

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
"""A session that commits when its block exits cleanly and rolls back otherwise."""

PauseHook = Callable[[AsyncSession, str, UUID | None, str], Awaitable[None]]
"""Called, in the pausing transaction, with the kind, the organization it is paused
for (`None` for the whole kind) and the reason."""

ScheduleTick = Callable[[AsyncSession], Awaitable[object]]
EndedHook = Callable[[str, dict[str, JsonValue], str], Awaitable[None]]
"""Settle what a job left outside the queue - a document, a sync log - once no
attempt of it is coming: `(kind, payload, why)`. Idempotent: it may find the
handler settled it already."""

Listen = Callable[[Callable[[str], None]], Coroutine[object, object, None]]
"""Runs until cancelled, calling back with the pool named by each notification."""

TRANSIENT = (SQLAlchemyError, OSError, TimeoutError)
"""What a database that is down, restarting or unreachable raises."""


@dataclass(frozen=True)
class WorkerSettings:
    worker_id: str
    hostname: str
    lease: timedelta = timedelta(seconds=60)
    heartbeat_every: float = 15.0
    rescue_every: float = 15.0
    schedule_every: float = 5.0
    poll_every: float = 5.0
    drain_timeout: float = 30.0
    breaker_deaths: int = 5
    """Worker deaths in a row, across a kind's jobs, that pause the kind."""
    retry_base: timedelta = timedelta(seconds=30)
    retry_cap: timedelta = timedelta(hours=1)
    outage_cap: float = 30.0
    """The longest pause between attempts to reach a database that is down."""
    settle_attempts: int = 5
    health_file: Path | None = None
    forget_workers_after: timedelta = timedelta(days=1)


@dataclass
class Worker:
    settings: WorkerSettings
    executors: Mapping[Pool, Executor]
    tasks: Mapping[str, TaskKind]
    sessions: SessionFactory
    on_pause: PauseHook
    on_ended: EndedHook
    schedule: ScheduleTick | None = None
    listen: Listen | None = None
    _wake: dict[Pool, asyncio.Event] = field(default_factory=dict, init=False)
    _running: set[asyncio.Task[None]] = field(default_factory=set, init=False)
    # The jobs whose outcome this worker still owes, and the only ones the
    # heartbeat extends. Keyed apart from `_running`: a job whose settlement was
    # abandoned leaves this set, so its lease runs out and the rescuer writes it
    # off, rather than being renewed for as long as the process lives (Codex,
    # #2248).
    _held: set[UUID] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self._wake = {pool: asyncio.Event() for pool in self.executors}

    async def run(self, stop: asyncio.Event) -> None:
        """Serve until `stop` is set, then finish or give back what is in hand, and return."""
        started: list[Executor] = []
        try:
            for executor in self.executors.values():
                started.append(executor)
                await executor.start()
            async with asyncio.TaskGroup() as group:
                upkeep = [
                    group.create_task(
                        self._every("heartbeat", self.settings.heartbeat_every, self._beat)
                    ),
                    group.create_task(
                        self._every("rescue", self.settings.rescue_every, self._rescue)
                    ),
                ]
                if self.schedule is not None:
                    upkeep.append(
                        group.create_task(
                            self._every(
                                "schedule", self.settings.schedule_every, self._fire_schedules
                            )
                        )
                    )
                if self.listen is not None:
                    upkeep.append(group.create_task(self.listen(self.wake)))
                dispatchers = [
                    group.create_task(self._dispatch(pool, stop), name=f"dispatch:{pool}")
                    for pool in self.executors
                ]
                await asyncio.gather(*dispatchers)
                await self._drain()
                for task in upkeep:
                    task.cancel()
        finally:
            for executor in started:
                await executor.close()
            await self._deregister()

    def wake(self, pool: str) -> None:
        """A job for `pool` has committed: stop waiting for the next poll."""
        with contextlib.suppress(ValueError):
            event = self._wake.get(Pool(pool))
            if event is not None:
                event.set()

    async def _dispatch(self, pool: Pool, stop: asyncio.Event) -> None:
        executor = self.executors[pool]
        wake = self._wake[pool]
        outages = 0
        while not stop.is_set():
            slot = await _first(executor.acquire(), stop)
            if slot is None:
                return
            wake.clear()
            try:
                job = await self._claim(pool)
            except TRANSIENT:
                executor.release(slot)
                outages += 1
                logger.warning("background_claim_failed", extra={"pool": pool}, exc_info=True)
                await _sleep_unless(stop, self._outage_pause(outages))
                continue
            outages = 0
            if job is None:
                executor.release(slot)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(_either(wake, stop), timeout=self.settings.poll_every)
                continue
            if stop.is_set():
                # The stop arrived while the claim awaited Postgres. Started now,
                # the job would have the drain's thirty seconds and then be
                # cancelled with its one attempt spent; it goes back unstarted.
                executor.release(slot)
                await self._unclaim(job)
                return
            self._held.add(job.id)
            task = asyncio.create_task(self._execute(executor, slot, job), name=f"job:{job.kind}")
            self._running.add(task)
            task.add_done_callback(self._finished)

    async def _claim(self, pool: Pool) -> ClaimedJob | None:
        async with self.sessions() as db:
            return await job_repo.claim(
                db, pool=pool.value, worker_id=self.settings.worker_id, lease=self.settings.lease
            )

    async def _execute(self, executor: Executor, slot: Slot, job: ClaimedJob) -> None:
        try:
            task = self.tasks.get(job.kind)
            if task is None:
                outcome: Outcome = Failed(
                    f"no task is declared for the job kind {job.kind!r}", permanent=True
                )
            else:
                outcome = await slot.run(
                    job.kind,
                    job.payload,
                    timeout=task.timeout,
                    attempt=Attempt(job.attempts, job.max_attempts),
                )
            await self._settle(job, outcome)
        except asyncio.CancelledError:
            # A shutdown, not a failure - but the attempt is spent: the job ran,
            # and what it did happened. It goes back if it has attempts left.
            await asyncio.shield(self._give_back(job))
            raise
        finally:
            self._held.discard(job.id)
            executor.release(slot)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._running.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("background_job_unsettled", exc_info=error)

    async def _settle(self, job: ClaimedJob, outcome: Outcome) -> None:
        """Write how `job` ended, retrying while the database is unreachable.

        A settle that never lands is not lost: the job leaves `_held`, so the
        heartbeat stops renewing it, its lease runs out and the rescuer writes it
        off as a worker death, with the attempt already counted.
        """
        for attempt in range(1, self.settings.settle_attempts + 1):
            try:
                async with self.sessions() as db:
                    ended = await self._record(db, job, outcome)
            except TRANSIENT:
                logger.warning(
                    "background_settle_failed",
                    extra={"job_id": str(job.id), "attempt": attempt},
                    exc_info=True,
                )
                await asyncio.sleep(self._outage_pause(attempt))
            else:
                # After the commit: the queue's word is final before anything
                # outside it is told, and a settler that fails cannot undo it.
                if ended is not None:
                    await self._ended(job.id, job.kind, job.payload, ended)
                return
        logger.error("background_settle_abandoned", extra={"job_id": str(job.id)})

    async def _ended(
        self, job_id: UUID, kind: str, payload: dict[str, JsonValue], why: str
    ) -> None:
        """Run the job's settler once, and record it run.

        A settler that fails leaves `settled_at` empty, and the rescuer's next
        pass runs it again: the queue's word is final, so nothing else would ever
        close the document or the sync log it left (Codex, #2248). It runs under
        the claim on the job's row, so the worker that saw the death and a
        rescuer reading the same end as owed never both run it (#2334).
        """
        try:
            async with self.sessions() as db:
                if not await job_repo.claim_settlement(db, job_id=job_id):
                    return
                await self.on_ended(kind, payload, why)
                await job_repo.mark_settled(db, job_id)
        except Exception:
            logger.exception("background_job_end_unsettled", extra={"job_id": str(job_id)})

    async def _record(self, db: AsyncSession, job: ClaimedJob, outcome: Outcome) -> str | None:
        """Write the outcome; answer why, when no attempt of the job is coming."""
        fence = job.attempts
        match outcome:
            case Succeeded(result=result):
                if not await job_repo.complete(db, job.id, fence=fence, result=result):
                    await self._lost(db, job)
                    return None
                await kind_repo.record_survival(db, job.kind, job.organization_id)
                return None
            case Failed(error=error, permanent=True):
                if not await job_repo.bury(db, job.id, fence=fence, error=error):
                    await self._lost(db, job)
                    return None
                await kind_repo.record_survival(db, job.kind, job.organization_id)
                return error
            case Failed(error=error):
                result = await job_repo.fail(
                    db, job.id, fence=fence, error=error, retry_in=self._retry_in(fence)
                )
                if result is FailOutcome.LOST:
                    await self._lost(db, job)
                    return None
                await kind_repo.record_survival(db, job.kind, job.organization_id)
                return None if result is FailOutcome.RETRYING else error
            case Died(reason=reason):  # pragma: no branch - `Outcome` has no fourth shape
                error = f"{reason} (attempt {fence} of {job.max_attempts})"
                result = await job_repo.fail(
                    db, job.id, fence=fence, error=error, retry_in=self._retry_in(fence)
                )
                if result is FailOutcome.LOST:
                    await self._lost(db, job)
                    return None
                logger.error(
                    "background_job_died",
                    extra={"job_id": str(job.id), "kind": job.kind, "reason": reason},
                )
                await self._count_death(db, job.kind, job.organization_id)
                return None if result is FailOutcome.RETRYING else reason

    async def _lost(self, db: AsyncSession, job: ClaimedJob) -> None:
        """The job was taken over while this worker still ran it: what it did may have happened twice."""
        logger.warning("background_lease_lost", extra={"job_id": str(job.id), "kind": job.kind})
        await kind_repo.record_lease_lost(db, job.kind, job.organization_id)

    async def _count_death(self, db: AsyncSession, kind: str, organization_id: UUID | None) -> None:
        """Count a death in the job's own scope: its organization's, or the kind's if it has none."""
        deaths = await kind_repo.record_death(db, kind, organization_id)
        if deaths < self.settings.breaker_deaths:
            return
        reason = (
            f"{deaths} jobs of this kind in a row ended with their worker process dead; "
            "it stays paused until it is resumed"
        )
        if await kind_repo.pause(db, kind, organization_id, reason=reason):
            logger.error(
                "background_kind_paused",
                extra={"kind": kind, "organization_id": str(organization_id), "deaths": deaths},
            )
            await self.on_pause(db, kind, organization_id, reason)

    async def _unclaim(self, job: ClaimedJob) -> None:
        try:
            async with self.sessions() as db:
                await job_repo.unclaim(db, job.id, fence=job.attempts)
        except TRANSIENT:
            # The lease runs out and the rescuer takes it back, the attempt spent.
            logger.warning(
                "background_unclaim_failed", extra={"job_id": str(job.id)}, exc_info=True
            )

    async def _give_back(self, job: ClaimedJob) -> None:
        try:
            async with self.sessions() as db:
                status = await job_repo.release(db, job.id, fence=job.attempts)
        except TRANSIENT:
            logger.warning(
                "background_release_failed", extra={"job_id": str(job.id)}, exc_info=True
            )
            return
        if status in ("dead", "cancelled"):
            await self._ended(job.id, job.kind, job.payload, "the worker stopped while it ran")

    async def _drain(self) -> None:
        """Let what is running finish for `drain_timeout`, then cancel the rest - which gives it back."""
        if not self._running:
            return
        _, pending = await asyncio.wait(set(self._running), timeout=self.settings.drain_timeout)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _beat(self) -> None:
        async with self.sessions() as db:
            await job_repo.extend_leases(
                db,
                worker_id=self.settings.worker_id,
                job_ids=list(self._held),
                lease=self.settings.lease,
            )
            await worker_repo.beat(
                db,
                worker_id=self.settings.worker_id,
                hostname=self.settings.hostname,
                pools=[pool.value for pool in self.executors],
            )
        if self.settings.health_file is not None:
            self.settings.health_file.touch()

    async def _rescue(self) -> None:
        async with self.sessions() as db:
            rescued = await job_repo.rescue_expired(db, retry_in=self.settings.retry_base)
            for job in rescued:
                logger.error(
                    "background_job_rescued",
                    extra={"job_id": str(job.id), "kind": job.kind, "dead": job.dead},
                )
                await self._count_death(db, job.kind, job.organization_id)
            await worker_repo.forget_silent_since(
                db, before=datetime.now(UTC) - self.settings.forget_workers_after
            )
            # Every end still owed a settlement: the ones just rescued, and any
            # whose settler failed before - a database that was down, a bug.
            owed = await job_repo.unsettled_ends(db)
        for end in owed:
            await self._ended(end.id, end.kind, end.payload, end.why)

    async def _fire_schedules(self) -> None:
        assert self.schedule is not None
        async with self.sessions() as db:
            await self.schedule(db)

    async def _every(self, name: str, seconds: float, work: Callable[[], Awaitable[None]]) -> None:
        """Run `work` every `seconds` until cancelled; a failure is logged and tried again."""
        outages = 0
        while True:
            try:
                await work()
            except TRANSIENT:
                outages += 1
                logger.warning("background_upkeep_failed", extra={"work": name}, exc_info=True)
                await asyncio.sleep(min(self._outage_pause(outages), seconds))
                continue
            outages = 0
            await asyncio.sleep(seconds)

    async def _deregister(self) -> None:
        try:
            async with self.sessions() as db:
                await worker_repo.remove(db, self.settings.worker_id)
        except TRANSIENT:
            logger.warning("background_worker_deregister_failed", exc_info=True)

    def _retry_in(self, attempts: int) -> timedelta:
        """Exponential from `retry_base`, capped, with a tenth either way so retries do not march in step."""
        base = min(self.settings.retry_base * 2 ** max(attempts - 1, 0), self.settings.retry_cap)
        return base * random.uniform(0.9, 1.1)  # noqa: S311 - jitter, not a secret

    def _outage_pause(self, outages: int) -> float:
        # Cap before exponentiation: min() cannot catch an overflow in its argument.
        exponent = min(outages - 1, ceil(log2(max(1.0, self.settings.outage_cap))))
        return min(2**exponent, self.settings.outage_cap) * random.uniform(0.5, 1.0)  # noqa: S311


async def _first[T](work: Awaitable[T], stop: asyncio.Event) -> T | None:
    """`work`'s result, or `None` if `stop` is set first - in which case `work` is cancelled."""
    working = asyncio.ensure_future(work)
    stopping = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({working, stopping}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopping.cancel()
    if working.done():
        return working.result()
    working.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await working
    return None


async def _either(first: asyncio.Event, second: asyncio.Event) -> None:
    waits = {asyncio.ensure_future(first.wait()), asyncio.ensure_future(second.wait())}
    try:
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for wait in waits:
            wait.cancel()


async def _sleep_unless(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)
