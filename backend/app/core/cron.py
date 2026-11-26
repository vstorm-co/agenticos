"""Cron expressions: whether one is usable, and when it next fires in a time zone.

Shared by everything the minute sweeps schedule - agent triggers, which keep a
schedule in UTC, and eval suites, which keep one in the zone their owner names.
"""

from datetime import UTC, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from croniter import CroniterBadDateError, croniter


def cron_has_next(expression: str) -> bool:
    """Whether a cron expression is valid *and* ever actually fires.

    `croniter.is_valid` checks only syntax, so `0 0 31 2 *` - the 31st of a
    February that never has one - passes it, and then `cron_next` exhausts its
    forward search and raises `CroniterBadDateError`, turning a user's cadence
    into a 500 at create or retime time. Resolving one occurrence here proves the
    expression has a future, so an unschedulable one is refused as a 422 naming
    the field instead.

    Only the five-field crontab shape is accepted. croniter also parses a
    six-field expression with a seconds column, but the sweeps that fire
    schedules tick once a minute, so `* * * * * *` would be accepted promising
    once a second and then fire once a minute, permanently overdue - a cadence
    the platform cannot honour is refused rather than quietly rounded.
    """
    if len(expression.split()) != 5:
        return False
    if not croniter.is_valid(expression):
        return False
    try:
        croniter(expression).get_next()
    except CroniterBadDateError:
        return False
    return True


def cron_next(expression: str, *, now: datetime, time_zone: str = "UTC") -> datetime:
    """The first instant a cron expression matches strictly after `now`, in UTC.

    The expression is read on the wall clock of `time_zone`, so `0 9 * * *` in
    `Europe/Warsaw` fires at nine in Warsaw on either side of a clock change.
    The expression and the zone are validated when they are stored, so ones read
    back off a row parse here.
    """
    local = now.astimezone(ZoneInfo(time_zone))
    # croniter ships no type information; the cast is what annotates the result.
    return cast(datetime, croniter(expression, local).get_next(datetime)).astimezone(UTC)


def cron_fires(
    expression: str, *, start: datetime, end: datetime, time_zone: str = "UTC", sample: int
) -> int:
    """How many times a cron expression fires after `start` and up to `end`.

    Enumerating every fire of a dense expression - `* * * * *` over a month is
    43,200 - would hold an API worker for seconds, so at most `sample` fires are
    walked and a cadence denser than that is extrapolated from the span they
    covered.
    """
    schedule = croniter(expression, start.astimezone(ZoneInfo(time_zone)))
    fires = 0
    while fires < sample:
        fired = cast(datetime, schedule.get_next(datetime))
        if fired > end:
            return fires
        fires += 1
    return round(fires * (end - start) / (fired - start))


def schedule_next(
    *,
    schedule_kind: str,
    interval_seconds: int | None,
    cron_expression: str | None,
    now: datetime,
    time_zone: str | None = None,
) -> datetime:
    """The next cron or interval occurrence, without catching up missed runs.

    Rows and request schemas validate cadence before use; a malformed internal
    call must fail rather than silently turning an unknown kind into an interval.
    This calculation is shared by routines and workflow schedules, independently
    of either execution runtime.
    """
    if schedule_kind == "cron":
        if cron_expression is None:
            raise ValueError("A cron schedule requires its expression")
        return cron_next(cron_expression, now=now, time_zone=time_zone or "UTC")
    if schedule_kind != "interval" or interval_seconds is None or interval_seconds < 1:
        raise ValueError("An interval schedule requires a positive interval")
    return now + timedelta(seconds=interval_seconds)
