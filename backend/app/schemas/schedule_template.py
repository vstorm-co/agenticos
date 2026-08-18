"""Read schemas for the schedule-templates catalog.

What the picker needs to pre-fill a new schedule from a template: the prompt and
the cadence to seed, and the label and description to draw the card.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.base import BaseSchema


class SuggestedCadenceRead(BaseSchema):
    """The cadence a template pre-fills - exactly one of interval or cron."""

    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None


class ScheduleTemplateRead(BaseSchema):
    """One ready-made schedule the picker can start a new one from."""

    key: str
    label: str
    description: str
    prompt: str
    suggested_cadence: SuggestedCadenceRead


class ScheduleTemplateList(BaseSchema):
    items: list[ScheduleTemplateRead]
    total: int
