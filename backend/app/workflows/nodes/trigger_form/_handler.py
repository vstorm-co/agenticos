"""`trigger.form`: a workflow anyone with its link starts by filling in a form.

Publishing a version with this trigger gives the workflow a public page at its
own address - the fields this node declares, under its title - and each
submission that fits them starts one run, as the member who published it. It
hands the graph what `trigger.manual` does: the answers as `payload`, typed by
the fields, and `triggered_by` naming the form.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from app.workflows.nodes.core_input._handler import (
    STATIC_PORTS,
    TriggerInputConfig,
    handle,
    ports_for,
)

MAX_TITLE = 120
MAX_TEXT = 1000


class FormTriggerConfig(TriggerInputConfig):
    """The page a form shows, and the fields it asks for."""

    title: str = Field(
        default="Form", min_length=1, max_length=MAX_TITLE, description="The page's heading"
    )
    description: str | None = Field(
        default=None,
        max_length=MAX_TEXT,
        description="Shown under the title: what the form is for",
    )
    submit_label: str = Field(
        default="Submit", min_length=1, max_length=40, description="The button's words"
    )
    success_message: str = Field(
        default="Thank you - your answers were sent.",
        min_length=1,
        max_length=MAX_TEXT,
        description="What the page says once the answers are in",
    )

    @model_validator(mode="after")
    def _asks_for_something(self) -> FormTriggerConfig:
        if not self.fields:
            raise ValueError("A form asks for at least one field")
        return self


__all__ = ["STATIC_PORTS", "FormTriggerConfig", "handle", "ports_for"]
