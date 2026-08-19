"""The trigger-templates catalog, and the promise each template makes.

The load itself is proven by import - `catalog.load` validates the JSON against
the frozen models at import time, so a malformed `trigger_templates.json` fails
collection here rather than a user's picker. What these add is the semantic
check the structural load cannot make: every schedule template's
`suggested_cadence` must be one a schedule would actually accept, every event
template must name the source whose message step offers it, and a template that
mixes the two shapes must be refused - a card filed under the wrong mode
pre-fills a form that cannot use it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.agent_trigger import TriggerCreate
from app.services import trigger_templates
from app.services.trigger_templates import SuggestedCadence, TriggerTemplate


def test_the_catalog_carries_both_kinds() -> None:
    kinds = {template.trigger_type for template in trigger_templates.CATALOG}
    assert kinds == {"schedule", "event"}


def test_every_schedule_templates_cadence_builds_a_valid_schedule() -> None:
    """The self-check: a template's `suggested_cadence` seeds a `TriggerCreate`,
    so a broken cron or an interval below the floor is refused here rather than
    when the create form pre-fills it."""
    for template in trigger_templates.CATALOG:
        if template.trigger_type != "schedule":
            continue
        cadence = template.suggested_cadence
        assert cadence is not None
        # Raises pydantic.ValidationError if the cadence is not schedulable.
        create = TriggerCreate(
            prompt=template.prompt,
            schedule_kind=cadence.schedule_kind,
            interval_seconds=cadence.interval_seconds,
            cron_expression=cadence.cron_expression,
        )
        assert create.trigger_type == "schedule"


def test_every_event_source_offers_at_least_one_template() -> None:
    """Every source the event form can pick has a starting point - a source
    whose message step offers nothing is back to the blank box the catalog
    exists to remove."""
    sources = {
        template.event_source
        for template in trigger_templates.CATALOG
        if template.trigger_type == "event"
    }
    assert sources == {"github", "email", "linkedin", "webhook"}


def test_every_template_key_is_unique() -> None:
    keys = [template.key for template in trigger_templates.CATALOG]
    assert len(keys) == len(set(keys))


def test_a_schedule_template_without_a_cadence_is_refused() -> None:
    with pytest.raises(ValidationError):
        TriggerTemplate(
            key="x",
            label="x",
            description="x",
            prompt="x",
            trigger_type="schedule",
        )


def test_an_event_template_with_a_cadence_is_refused() -> None:
    """The mixed shape - an event card that also carries a cadence - is the one
    a picker would file under both modes, so the model refuses it outright."""
    with pytest.raises(ValidationError):
        TriggerTemplate(
            key="x",
            label="x",
            description="x",
            prompt="x",
            trigger_type="event",
            event_source="github",
            suggested_cadence=SuggestedCadence(schedule_kind="interval", interval_seconds=3600),
        )


def test_an_event_template_without_a_source_is_refused() -> None:
    with pytest.raises(ValidationError):
        TriggerTemplate(
            key="x",
            label="x",
            description="x",
            prompt="x",
            trigger_type="event",
        )
