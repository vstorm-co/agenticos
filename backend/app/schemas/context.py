"""Schemas for context files."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

ContextModeLiteral = Literal["inject", "link"]


class ContextFileRead(BaseSchema):
    id: UUID
    name: str
    description: str | None = None
    content: str
    format: str
    mode: ContextModeLiteral
    enabled: bool
    visibility: str
    owner_user_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContextFileSummary(BaseSchema):
    """A context file as the listing shows it - without the body.

    The body is the whole point of an injected file (it becomes prompt) and of a
    linked one (the model loads it on demand). A listing that carried every body
    would ship an agent's entire standing context to draw one picker.
    """

    id: UUID
    name: str
    description: str | None = None
    format: str
    mode: ContextModeLiteral
    enabled: bool
    size_bytes: int = Field(description="The body's size, so the listing can hint at its weight")


class ContextFileList(BaseSchema):
    items: list[ContextFileSummary]
    total: int


class ContextFileCreate(BaseSchema):
    name: str = Field(
        min_length=1,
        max_length=64,
        description="How the file is referred to; unique per organization",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="What is in it, so a linked file can be chosen without loading it",
    )
    content: str = Field(default="", description="The file body, as text")
    format: str = Field(
        default="md",
        min_length=1,
        max_length=16,
        description="A hint for fencing and rendering, e.g. `md`, `txt`, `json`, `yaml`, `csv`",
    )
    mode: ContextModeLiteral = Field(
        default="inject",
        description="`inject` into the system prompt, or `link` for on-demand reading via a tool",
    )


class ContextFileUpdate(BaseSchema):
    description: str | None = Field(default=None, max_length=500)
    content: str | None = None
    format: str | None = Field(default=None, min_length=1, max_length=16)
    mode: ContextModeLiteral | None = None
    enabled: bool | None = None
