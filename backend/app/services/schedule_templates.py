"""A curated catalog of schedule *templates* - ready-made prompts and cadences.

A schedule fires an agent on the clock with a stored prompt. Starting from a
blank prompt box is the hard part of setting one up, so this is a handful of
seeded starting points - "summarise my open pull requests every weekday
morning", "triage new issues each morning" - each pairing a useful prompt with a
sane cadence the picker can pre-fill.

A template is *setup* data, not a kind of trigger: it seeds a `TriggerCreate` and
plays no part once the schedule exists, exactly as a portal preset seeds an event
trigger. Its `suggested_cadence` is one of the two schedule shapes - an
`interval` in seconds or a UTC `cron_expression` - so the create form fills the
same fields a user would type by hand.

Hand-maintained data, like `portals.json` beside it: adding a template is a JSON
edit, never code, and `catalog.load` validates every field against these frozen
models at import, so a malformed file refuses to start the app rather than
shipping a picker with a hole. The cron expressions here are UTC, matching how a
schedule stores and compares its next fire; `tests/test_schedule_templates.py`
proves every template's cadence is one a schedule would actually accept.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.core import catalog


class SuggestedCadence(BaseModel):
    """The cadence a template pre-fills - exactly one of interval or cron.

    Mirrors a schedule's two shapes: `interval` carries `interval_seconds`, `cron`
    carries a UTC `cron_expression`. The catalog self-check builds a `TriggerCreate`
    from each, so a template that names a shape without its field never ships.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None


class ScheduleTemplate(BaseModel):
    """One ready-made schedule: a prompt and the cadence to run it on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    description: str
    prompt: str
    suggested_cadence: SuggestedCadence


# Validated against the models at import, like every catalog here: a malformed
# template stops the deployment instead of shipping a picker with a hole.
CATALOG: tuple[ScheduleTemplate, ...] = catalog.load(
    "schedule_templates.json", TypeAdapter(tuple[ScheduleTemplate, ...])
)

BY_KEY: dict[str, ScheduleTemplate] = {template.key: template for template in CATALOG}


def get_template(key: str) -> ScheduleTemplate | None:
    """The template a key names, or None if it names nothing."""
    return BY_KEY.get(key)
