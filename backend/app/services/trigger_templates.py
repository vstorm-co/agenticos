"""A curated catalog of trigger *templates* - ready-made prompts for both kinds.

Starting from a blank prompt box is the hard part of setting a trigger up, so
this is a handful of seeded starting points, split by the flow that offers them.
A **schedule** template pairs a prompt with a sane cadence the create form
pre-fills - "summarise my open pull requests every weekday morning". An
**event** template pairs a prompt with the source whose deliveries it reads -
"triage the new issue" for GitHub, "draft a reply" for email - and is offered
only on that source's message step, because a prompt written for an issue makes
no sense against an inbound email.

A template is *setup* data, not a kind of trigger: it seeds a `TriggerCreate`
and plays no part once the trigger exists, exactly as a portal preset seeds an
event trigger. The two shapes never mix - the validator refuses a template that
carries both a cadence and a source, or neither, so the catalog cannot hold a
card the picker would file under the wrong mode.

Hand-maintained data, like `portals.json` beside it: adding a template is a JSON
edit, never code, and `catalog.load` validates every field against these frozen
models at import, so a malformed file refuses to start the app rather than
shipping a picker with a hole. The cron expressions here are UTC, matching how a
schedule stores and compares its next fire; `tests/test_trigger_templates.py`
proves every schedule template's cadence is one a schedule would actually accept.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from app.core import catalog


class SuggestedCadence(BaseModel):
    """The cadence a schedule template pre-fills - exactly one of interval or cron.

    Mirrors a schedule's two shapes: `interval` carries `interval_seconds`, `cron`
    carries a UTC `cron_expression`. The catalog self-check builds a `TriggerCreate`
    from each, so a template that names a shape without its field never ships.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule_kind: Literal["interval", "cron"]
    interval_seconds: int | None = None
    cron_expression: str | None = None


class TriggerTemplate(BaseModel):
    """One ready-made trigger: a prompt, and the mode whose flow offers it.

    `trigger_type` decides which create flow shows the card: a `schedule`
    template carries the `suggested_cadence` to pre-fill, an `event` template
    the `event_source` whose message step offers it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    description: str
    prompt: str
    trigger_type: Literal["schedule", "event"]
    suggested_cadence: SuggestedCadence | None = None
    event_source: Literal["github", "email", "webhook"] | None = None

    @model_validator(mode="after")
    def _shape_matches_mode(self) -> TriggerTemplate:
        """A schedule carries a cadence and no source; an event the reverse.

        A card that broke this would be filed under a mode whose create form
        cannot use what it pre-fills, so the file refuses to load instead.
        """
        if self.trigger_type == "schedule":
            if self.suggested_cadence is None or self.event_source is not None:
                raise ValueError("a schedule template carries a cadence and no event source")
        elif self.suggested_cadence is not None or self.event_source is None:
            raise ValueError("an event template carries an event source and no cadence")
        return self


# Validated against the models at import, like every catalog here: a malformed
# template stops the deployment instead of shipping a picker with a hole.
CATALOG: tuple[TriggerTemplate, ...] = catalog.load(
    "trigger_templates.json", TypeAdapter(tuple[TriggerTemplate, ...])
)
