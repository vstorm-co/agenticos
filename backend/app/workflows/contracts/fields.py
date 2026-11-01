"""The typed fields a trigger declares - what a run starts with, asked for by name.

A leaf, so a schema can name a field without importing a node and the execution
service behind it: the Manual, API, Form and Called by a workflow triggers declare
these, and a form's public page draws them.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_OPTIONS = 50

InputFieldType = Literal["text", "number", "integer", "boolean", "date", "choice"]


class InputField(BaseModel):
    """One value a run starts with, asked for by name in the Run dialog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
        description="The key in the run's input, and in payload for a binding",
    )
    label: str | None = Field(default=None, max_length=120, description="Shown in the Run form")
    type: InputFieldType = "text"
    required: bool = True
    description: str | None = Field(default=None, max_length=500)
    options: list[str] = Field(
        default_factory=list, max_length=MAX_OPTIONS, description="What a choice offers"
    )

    @model_validator(mode="after")
    def _fits_its_type(self) -> InputField:
        # A name the generated payload model would inherit from `BaseModel`
        # (`copy`, `json`, ...) cannot be one of its fields.
        if hasattr(BaseModel, self.name):
            raise ValueError(f"{self.name!r} is reserved; name the field something else")
        if self.type == "choice":
            if not self.options or any(not option.strip() for option in self.options):
                raise ValueError("A choice needs at least one option, and none of them blank")
            if len(set(self.options)) != len(self.options):
                raise ValueError("A choice offers each option once")
        elif self.options:
            raise ValueError("Only a choice has options")
        return self
