"""Read schemas for the trigger-templates catalog.

What the picker needs to pre-fill a new trigger from a template: the prompt to
seed, the mode that decides which flow offers the card - a cadence for a
schedule, an event source for an event - and the label and description to draw
it.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.base import BaseSchema


class SuggestedCadenceRead(BaseSchema):
    """The cadence a schedule template pre-fills - exactly one of interval or cron."""

    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None


class TriggerTemplateRead(BaseSchema):
    """One ready-made trigger the picker can start a new one from."""

    key: str
    label: str
    description: str
    prompt: str
    trigger_type: Literal["schedule", "event"]
    suggested_cadence: SuggestedCadenceRead | None = None
    event_source: Literal["github", "email", "webhook"] | None = None


class TriggerTemplateList(BaseSchema):
    items: list[TriggerTemplateRead]
    total: int
