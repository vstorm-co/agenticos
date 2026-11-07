"""The draft wire format: what the tool validates and every surface rebuilds.

A draft card is never stored as a result of its own. The console and the
share-by-link page rebuild it from the stored call's arguments, so this module
holds the limits and the one parser both use. It imports no agent machinery, so
a delivery layer can read the format without pulling a toolset in behind it.
"""

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

if TYPE_CHECKING:
    from app.agents.spec import AgentSpec

DRAFTS_CAPABILITY_ID = "drafts"
WRITE_DRAFT = "write_draft"


def draft_tool_names(spec: AgentSpec) -> frozenset[str]:
    for binding in spec.capabilities:
        if binding.id == DRAFTS_CAPABILITY_ID and binding.enabled:
            override = binding.tool_overrides.get(WRITE_DRAFT)
            return frozenset(
                {override.name if override is not None and override.name else WRITE_DRAFT}
            )
    return frozenset()


DRAFTED = "Drafted "
"""What a tool result opens with when a card was made. Anything else is a refusal."""

MAX_VERSIONS = 5
MAX_FIELDS = 10
MAX_TEXT_CHARS = 20_000

_FORMAT = re.compile(r"^[a-z0-9][a-z0-9+#.-]{0,23}$")


class DraftField(BaseModel):
    """One part of a draft, pasted on its own: a subject, a body."""

    name: str | None = Field(default=None, max_length=40)
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    format: str = "text"

    @field_validator("text")
    @classmethod
    def _not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("text must not be blank")
        return text

    @field_validator("format")
    @classmethod
    def _known_shape(cls, value: str) -> str:
        if not _FORMAT.match(value):
            raise ValueError(
                "format must be a short lower-case word such as text, markdown or python"
            )
        return value


class DraftVersion(BaseModel):
    """One take on the draft; its label is the tab when there are several."""

    label: str | None = Field(default=None, max_length=30)
    fields: list[DraftField] = Field(min_length=1, max_length=MAX_FIELDS)


class DraftCard(BaseModel):
    """A draft as the person sees it: a titled card of one to five versions."""

    title: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=40)
    versions: list[DraftVersion] = Field(min_length=1, max_length=MAX_VERSIONS)

    @model_validator(mode="after")
    def _versions_tell_apart(self) -> DraftCard:
        if len(self.versions) < 2:
            return self
        labels = [(version.label or "").strip().lower() for version in self.versions]
        if not all(labels):
            raise ValueError("every version needs a label when there are two or more")
        if len(set(labels)) != len(labels):
            raise ValueError("version labels must differ from each other")
        return self


def parse_draft_card(args: Mapping[str, object] | None) -> DraftCard | None:
    """The card a stored call's arguments describe, or None when they no longer parse."""
    if args is None:
        return None
    try:
        return DraftCard.model_validate(args)
    except ValidationError:
        return None
