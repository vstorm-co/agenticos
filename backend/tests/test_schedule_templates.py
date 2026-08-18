"""The schedule-templates catalog, and the promise each template makes.

The load itself is proven by import - `catalog.load` validates the JSON against
the frozen models at import time, so a malformed `schedule_templates.json` fails
collection here rather than a user's picker. What these add is the semantic check
the structural load cannot make: every template's `suggested_cadence` must be one
a schedule would actually accept, so a template with a broken cron or a missing
interval is caught in CI rather than the first time someone picks the card.
"""

from __future__ import annotations

from app.schemas.agent_trigger import TriggerCreate
from app.services import schedule_templates


def test_the_catalog_loads_and_is_not_empty() -> None:
    assert schedule_templates.CATALOG


def test_every_templates_cadence_builds_a_valid_schedule() -> None:
    """The self-check: a template's `suggested_cadence` seeds a `TriggerCreate`,
    so a broken cron or an interval below the floor is refused here rather than
    when the create form pre-fills it."""
    for template in schedule_templates.CATALOG:
        cadence = template.suggested_cadence
        # Raises pydantic.ValidationError if the cadence is not schedulable.
        create = TriggerCreate(
            prompt=template.prompt,
            schedule_kind=cadence.schedule_kind,
            interval_seconds=cadence.interval_seconds,
            cron_expression=cadence.cron_expression,
        )
        assert create.trigger_type == "schedule"


def test_every_template_key_is_unique() -> None:
    keys = [template.key for template in schedule_templates.CATALOG]
    assert len(keys) == len(set(keys))
