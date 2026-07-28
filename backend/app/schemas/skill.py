"""Schemas for skills."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class SkillResourceRead(BaseSchema):
    """One file a skill can hand the model when it needs the detail."""

    id: UUID
    name: str
    description: str | None = None
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillResourceSummary(BaseSchema):
    """A file as a listing names it — without the body.

    The bodies are the whole point of progressive disclosure: an agent reads the
    names, decides, and loads one. A list that carried every body would defeat
    the mechanism it is describing.
    """

    id: UUID
    name: str
    description: str | None = None
    size_bytes: int


class SkillResourceCreate(BaseSchema):
    name: str = Field(
        min_length=1,
        max_length=128,
        description="The filename the model asks for, e.g. `reference.md` or `forms/w9.md`",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="What is in it, so the model can decide without loading it",
    )
    content: str = Field(default="", description="The file body")


class SkillResourceList(BaseSchema):
    items: list[SkillResourceRead]
    total: int


class SkillResourceUpdate(BaseSchema):
    description: str | None = Field(default=None, max_length=500)
    content: str | None = None


class SkillRead(BaseSchema):
    id: UUID
    name: str
    description: str
    content: str
    enabled: bool
    version: int
    visibility: str
    owner_user_id: UUID | None = None
    resources: list[SkillResourceSummary] = Field(
        default_factory=list,
        description="The files this skill carries beyond its body, without their contents",
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillSummary(BaseSchema):
    """What the Builder's picker shows — the body is loaded on demand."""

    id: UUID
    name: str
    description: str
    enabled: bool


class SkillList(BaseSchema):
    items: list[SkillSummary]
    total: int


class SkillCreate(BaseSchema):
    name: str = Field(
        min_length=1,
        max_length=64,
        description="How the model refers to this skill; unique per organization",
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        description="The one line the model reads before deciding to load the body",
    )
    content: str = Field(default="", description="The skill body, in Markdown")


class SkillUpdate(BaseSchema):
    description: str | None = Field(default=None, max_length=500)
    content: str | None = None
    enabled: bool | None = None


class LibrarySkillRead(BaseSchema):
    """One skill this deployment ships with, as the gallery shows it."""

    key: str = Field(description="The folder it lives in — how an install names it")
    name: str
    description: str
    content: str = Field(description="The body, so the gallery can show it before installing")
    resources: list[SkillResourceSummary] = Field(default_factory=list)
    installed: bool = Field(
        default=False,
        description="Whether this organization already has a skill by that name",
    )


class LibrarySkillList(BaseSchema):
    items: list[LibrarySkillRead]
    total: int
