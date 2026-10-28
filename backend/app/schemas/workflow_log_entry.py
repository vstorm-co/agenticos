"""The wire shapes of a workflow's log."""

from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import Field

from app.schemas.base import BaseSchema


@dataclass(frozen=True, slots=True)
class LogFilters:
    """What a log listing is narrowed to; test runs only when asked for.

    `outcome` lists the ports a line may have left by: any of them matches, and a value of
    ports joined by `", "` counts as each of them.
    `run` is a whole run id or the start of one (hex digits and dashes).
    """

    node_instance_id: UUID | None = None
    outcome: list[str] | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    query: str | None = None
    include_test: bool = False
    run: str | None = None


LOG_SUMMARY_DAYS = (7, 30, 90)
"""The windows the log's counts can cover, in days."""

_UUID_SHAPE = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
_HEX = frozenset("0123456789abcdefABCDEF")


def is_run_filter(run: str) -> bool:
    """A whole run id (dashes or not) or its first 4 or more characters, dashes where
    an id has them: the text cast a prefix is compared with."""
    if len(run) == 32:
        return all(char in _HEX for char in run)
    if not 4 <= len(run) <= len(_UUID_SHAPE):
        return False
    return all(
        char == "-" if shape == "-" else char in _HEX
        for char, shape in zip(run, _UUID_SHAPE, strict=False)
    )


@cache
def _time_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def is_time_zone(name: str) -> bool:
    """Whether `name` is an IANA time zone name, such as `Europe/Warsaw`."""
    return name in _time_zones()


class WorkflowLogEntryRead(BaseSchema):
    """One line a step's Quick Log wrote."""

    id: UUID
    workflow_id: UUID
    run_id: UUID
    node_instance_id: UUID
    step_label: str
    outcome: str
    status: str
    message: str
    is_test: bool
    is_pinned: bool
    created_at: datetime


class WorkflowLogEntryList(BaseSchema):
    items: list[WorkflowLogEntryRead]
    total: int


class WorkflowLogDay(BaseSchema):
    """One day of a workflow's log: how many lines left by each outcome."""

    day: date
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Lines that day by outcome - a port, or `error`; outcomes with none are absent",
    )


class WorkflowLogSummary(BaseSchema):
    """A workflow's log counted per day and outcome over the last `days` days."""

    days: int
    total: int
    by_day: list[WorkflowLogDay] = Field(description="Every day of the window, oldest first")


class WorkflowRecentLogEntry(WorkflowLogEntryRead):
    """A line of the log, with the name of the workflow it belongs to."""

    workflow_name: str


class WorkflowRecentLogs(BaseSchema):
    """The newest real-run lines across the workflows a caller may view."""

    items: list[WorkflowRecentLogEntry]
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Lines written in the last 24 hours by outcome; outcomes with none are absent",
    )
