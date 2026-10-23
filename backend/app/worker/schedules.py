"""The deployment's own recurring jobs, and how a worker fires them (#2219).

Every schedule is an interval on a fixed grid: a schedule declared every hour
fires at the same minute past each hour however late any one firing was. The
grid is kept in `background_schedules.next_run_at`, so a restart picks up
where the last worker left off.

Two decisions shape what a late or overlapping occurrence does (both from the
#2219 Q&A, and both in n8n's durable scheduler the same way):

* **Late.** An occurrence up to `grace` late fires as if on time - a worker
  restarting for a deploy does not cost the minute sweeps their tick. Later
  than that, `misfire` decides: `latest` fires once for the whole backlog, for
  the most recent occurrence that passed; `skip` waits for the next one.
  Nothing ever fires once per missed occurrence: the sweeps work over current
  state, so a backlog of them is the same work done many times.
* **Overlap.** An occurrence that arrives while the job the previous one fired
  is still queued or running does what `overlap` says: `skip` drops it, `queue`
  lets one wait behind the running one, `allow` runs it alongside.
"""

import enum
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_schedule import BackgroundSchedule
from app.repositories import background_job as job_repo
from app.repositories import background_schedule as schedule_repo
from app.services.background_jobs import enqueue
from app.worker import jobs
from app.worker.jobs import Task, Tick

logger = logging.getLogger(__name__)

_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)


class Overlap(enum.StrEnum):
    SKIP = "skip"
    QUEUE = "queue"
    ALLOW = "allow"


class Misfire(enum.StrEnum):
    LATEST = "latest"
    SKIP = "skip"


@dataclass(frozen=True)
class Schedule:
    name: str
    task: Task[Tick]
    every: timedelta
    overlap: Overlap = Overlap.SKIP
    misfire: Misfire = Misfire.LATEST
    grace: timedelta = _MINUTE


SCHEDULES: tuple[Schedule, ...] = (
    # Fire the agent triggers that have come due.
    Schedule("check-agent-triggers", jobs.CHECK_AGENT_TRIGGERS, _MINUTE),
    # Read the connected accounts nobody pushes to. Its own schedule rather than
    # work inside the trigger check: the two fail independently - a Gmail outage
    # must not stop a cron schedule firing.
    Schedule("poll-portal-grants", jobs.POLL_PORTAL_GRANTS, _MINUTE),
    # Send queued notifications: a pending delivery waits at most one tick.
    Schedule("deliver-notifications", jobs.DELIVER_NOTIFICATIONS, _MINUTE),
    # Queue a sync for each source that has come due.
    Schedule("dispatch-due-syncs", jobs.DISPATCH_DUE_SYNCS, _MINUTE),
    # Destroy the remote sandboxes a deleted conversation or project left behind
    # (#2209). Each tombstone carries its own backoff, so most ticks find none due.
    Schedule("retry-sandbox-destroys", jobs.RETRY_SANDBOX_DESTROYS, _MINUTE),
    # A call a dead worker left is billed by the minute, and its heartbeat goes
    # stale 45 s after the worker died (#54).
    Schedule("reap-voice-calls", jobs.REAP_VOICE_CALLS, _MINUTE),
    # A run whose process died stops beating; a chat says "Working" over it
    # until this ends it, so it is looked for every minute (#2301).
    Schedule("reap-stale-runs", jobs.REAP_STALE_RUNS, _MINUTE),
    # Queue a look for each watch that has come due (#2301). Each watch keeps its
    # own cadence, the most often fifteen minutes; this only finds whose turn it is.
    Schedule("watch-sweep", jobs.WATCH_SWEEP, _MINUTE),
    # Renew OAuth tokens near expiry and dial every organization server: often
    # enough that a dead grant is noticed within a coffee break.
    Schedule("sweep-mcp-connections", jobs.SWEEP_MCP_CONNECTIONS, timedelta(minutes=15)),
    # Hourly, against thresholds measured in hours or days: an approval or an
    # invitation expiring forty minutes late has cost nobody anything.
    # The platform's look at each person's week (#2301): hourly, because who is
    # due depends on their own clock - each is thought about once a night, early
    # in their morning, so what it proposes is waiting when they start.
    Schedule("proactive-sweep", jobs.PROACTIVE_SWEEP, _HOUR),
    Schedule("expire-approvals", jobs.EXPIRE_APPROVALS, _HOUR),
    Schedule("expire-invitations", jobs.EXPIRE_INVITATIONS, _HOUR),
    # A teardown reservation whose drop failed for good blocks its collection's
    # name with nothing left to reattempt it (#1364).
    Schedule("sweep-teardown-reservations", jobs.SWEEP_TEARDOWN_RESERVATIONS, _HOUR),
    # Daily: retention windows are measured in days, so the hour a row leaves is
    # nobody's business.
    Schedule("sweep-sandbox-operations", jobs.SWEEP_SANDBOX_OPERATIONS, _DAY),
    Schedule("apply-retention", jobs.APPLY_RETENTION, _DAY),
    Schedule("sweep-notifications", jobs.SWEEP_NOTIFICATIONS, _DAY),
    Schedule("sweep-background-jobs", jobs.SWEEP_BACKGROUND_JOBS, _DAY),
    # Generated images, speech and video past `GENERATED_MEDIA_RETENTION_DAYS` (#2310).
    Schedule("sweep-generated-media", jobs.SWEEP_GENERATED_MEDIA, _DAY),
    # A report covers the period its occurrence names, so one that arrives while
    # the last is still sending waits rather than being dropped: a skipped tick
    # would be a week nobody is ever sent.
    Schedule("weekly-usage-report", jobs.WEEKLY_USAGE_REPORT, 7 * _DAY, overlap=Overlap.QUEUE),
    Schedule("monthly-usage-report", jobs.MONTHLY_USAGE_REPORT, 30 * _DAY, overlap=Overlap.QUEUE),
)


async def declare(db: AsyncSession, schedules: Sequence[Schedule], *, now: datetime) -> None:
    """Write `schedules` to the database, and forget the ones no longer declared.

    A schedule new to the database first fires within a minute of `now`, each
    a share of that minute after the last, so a fresh deployment's sweeps do not
    all wake at once.
    """
    for index, schedule in enumerate(schedules):
        await schedule_repo.declare(
            db,
            name=schedule.name,
            kind=schedule.task.kind,
            interval_seconds=int(schedule.every.total_seconds()),
            overlap=schedule.overlap.value,
            misfire=schedule.misfire.value,
            grace_seconds=int(schedule.grace.total_seconds()),
            now=now,
            first_run_at=now + _spread(index, len(schedules)),
        )
    removed = await schedule_repo.forget_undeclared(db, declared=[s.name for s in schedules])
    if removed:
        logger.info("background_schedules_forgotten", extra={"count": removed})


async def fire_due(
    db: AsyncSession, schedules: Sequence[Schedule], *, now: datetime, limit: int = 50
) -> list[str]:
    """Fire every schedule due at `now`, once each, and move it on. Answers the names that fired.

    The claimed rows stay locked until `db` commits, together with the jobs they
    fired, so two workers ticking at the same instant fire each schedule once.
    """
    declared = {schedule.name: schedule for schedule in schedules}
    fired: list[str] = []
    for row in await schedule_repo.claim_due(db, now=now, limit=limit):
        schedule = declared.get(row.name)
        if schedule is None:
            continue
        occurrence, next_run_at = _occurrences(row, now=now)
        job_id = None
        if occurrence is not None:
            job_id = await _fire(db, schedule, occurrence)
        await schedule_repo.advance(
            db,
            row.name,
            next_run_at=next_run_at,
            fired_at=now if job_id is not None else None,
            job_id=job_id,
        )
        if job_id is not None:
            fired.append(row.name)
    return fired


def _occurrences(row: BackgroundSchedule, *, now: datetime) -> tuple[datetime | None, datetime]:
    """Which occurrence to fire for a due row, if any, and when it is next due.

    The next occurrence is the first on the row's grid after `now`. The one to
    fire is the row's own when it is within grace, the most recent one that
    passed when the backlog is fired as one, and none when it is skipped.
    """
    interval = timedelta(seconds=row.interval_seconds)
    late = now - row.next_run_at
    passed = math.floor(late / interval)
    next_run_at = row.next_run_at + interval * (passed + 1)
    if late <= timedelta(seconds=row.grace_seconds):
        return row.next_run_at, next_run_at
    if row.misfire == Misfire.LATEST:
        return row.next_run_at + interval * passed, next_run_at
    return None, next_run_at


async def _fire(db: AsyncSession, schedule: Schedule, occurrence: datetime) -> UUID | None:
    if schedule.overlap is Overlap.SKIP and await job_repo.has_active_for_schedule(
        db, schedule.name
    ):
        logger.info("background_schedule_overlap_skipped", extra={"schedule": schedule.name})
        return None
    key = f"schedule:{schedule.name}" if schedule.overlap is Overlap.QUEUE else None
    return await enqueue(
        db,
        schedule.task,
        Tick(scheduled_for=occurrence),
        schedule_name=schedule.name,
        dedupe_key=key,
        concurrency_key=key,
    )


def _spread(index: int, count: int) -> timedelta:
    """A share of a minute: spread enough to keep the sweeps apart, and no daily one waits a day."""
    return _MINUTE * index / max(count, 1)
