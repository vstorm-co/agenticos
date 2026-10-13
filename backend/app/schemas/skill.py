"""Schemas for skills."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.agents.capabilities import all_capabilities
from app.schemas.base import BaseSchema
from app.schemas.resource_grant import AudienceChoice
from app.schemas.resource_usage import AgentUsage

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
"""The Agent Skills name format: lowercase letters and digits, joined by hyphens.

A skill's name is the id the model passes to `load_capability`, and models
trained on this format write the hyphenated form whatever the catalog lists. A
gallery skill called `Product description writer` was loaded as
`product-description-writer`, which is no id at all, and the second wrong guess
ended the turn (#1911).
"""


def skill_name_refusal(name: str) -> str | None:
    """Why `name` cannot be a skill's name, or None when it can.

    A skill is a deferred capability, filed under its name in the same namespace
    as `knowledge`, `planning` and the rest - so a skill called `planning` bound
    to an agent that also has the planning capability is a duplicate id the
    library refuses before the first token. Checked on the request schema and
    again in `SkillService.create`, which an applied skill proposal reaches
    without one, and at publish for the skills that predate this (#1704 review).
    """
    if not SKILL_NAME_PATTERN.fullmatch(name):
        return (
            "Use lowercase letters, digits and hyphens, such as 'refund-policy' - "
            "the name is the id a model loads the skill by, and it writes names in "
            "that form"
        )
    if name in {definition.id for definition in all_capabilities()}:
        return (
            f"'{name}' is the name of a capability this platform offers, and a skill "
            "is a capability too - pick another name"
        )
    return None


class SkillResourceRead(BaseSchema):
    """One file a skill can hand the model when it needs the detail."""

    id: UUID
    name: str
    description: str | None = None
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SkillResourceSummary(BaseSchema):
    """A file as a listing names it - without the body.

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
    category: str | None = None
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
    """What the Builder's picker shows - the body is loaded on demand."""

    id: UUID
    name: str
    description: str
    category: str | None = None
    enabled: bool
    file_count: int = Field(description="How many files the skill carries beyond its body")
    built_in: bool = Field(
        description="Whether this skill shipped with the deployment, by library name"
    )
    excerpt: str = Field(
        default="",
        description=(
            "The body's first lines, front matter dropped and bounded, so a card can "
            "show what the skill says without the listing carrying every body"
        ),
    )
    used_by: list[AgentUsage] = Field(
        default_factory=list,
        description=(
            "The agents whose draft binds this, among those the caller may see - so a "
            "card says where it is used, or that it is used nowhere yet"
        ),
    )
    shared_groups: list[str] = Field(
        default_factory=list,
        description="The groups this is shared with, by name - the departments it belongs to.",
    )


class SkillList(BaseSchema):
    items: list[SkillSummary]
    total: int
    categories: list[str] = Field(
        default_factory=list,
        description=(
            "Every distinct category in the organization - the filter's choices, "
            "unaffected by the search and paging that shaped `items`"
        ),
    )
    suggested_categories: list[str] = Field(
        default_factory=list,
        description=(
            "The deployment's predefined shelf names, for the category pickers - "
            "a suggestion beside the free-typed value, never a constraint on it"
        ),
    )


class SkillCreate(AudienceChoice):
    name: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "How the model refers to this skill: lowercase letters, digits and hyphens, "
            "unique per organization"
        ),
    )

    @field_validator("name")
    @classmethod
    def _not_a_capability_name(cls, name: str) -> str:
        refusal = skill_name_refusal(name)
        if refusal is not None:
            raise ValueError(refusal)
        return name

    description: str = Field(
        min_length=1,
        max_length=500,
        description="The one line the model reads before deciding to load the body",
    )
    content: str = Field(default="", description="The skill body, in Markdown")
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="A grouping label for the listing, e.g. `marketing` or `devops`",
    )


class SkillUpdate(BaseSchema):
    description: str | None = Field(default=None, max_length=500)
    content: str | None = None
    enabled: bool | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)


class GallerySkillRead(BaseSchema):
    """One gallery skill as the picker shows it - never the body."""

    key: str = Field(description="`<industry>/<folder>`, how an install request names it")
    name: str
    description: str
    category: str | None = None
    installed: bool = Field(
        description="Whether this organization already has a skill by this name",
    )


class GalleryIndustryRead(BaseSchema):
    """One industry shelf, and what is on it."""

    id: str = Field(description="The directory name - the console maps it to a label and an icon")
    skills: list[GallerySkillRead]


class SkillGallery(BaseSchema):
    industries: list[GalleryIndustryRead]


class GalleryInstallRequest(BaseSchema):
    """Which gallery skills to copy in - one, or a whole shelf."""

    keys: list[str] = Field(min_length=1, max_length=200)


class GalleryInstallResult(BaseSchema):
    """What the install did, per skill, so a partial result is legible.

    A key already present is *skipped* rather than refused: installing a shelf
    where one skill is already there must not fail the other nine, and the
    organization's own edited copy is never overwritten.
    """

    installed: list[str] = Field(description="Names created by this request")
    skipped: list[str] = Field(description="Names the organization already had")
    unknown: list[str] = Field(description="Keys this deployment does not ship")
