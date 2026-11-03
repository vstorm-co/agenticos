"""Schemas for skill versions and forks."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.models.skill_version import SkillVersionSource
from app.schemas.base import BaseSchema


class VersionRef(BaseSchema):
    """A version as another one points at it."""

    id: UUID
    number: int
    fork_id: UUID | None = Field(description="The fork it belongs to; null for the main line")


class PersonRef(BaseSchema):
    id: UUID
    name: str | None = Field(description="Null for somebody who is no longer a member")


class SkillVersionSummary(BaseSchema):
    """One version as the History tab lists it, without its text."""

    id: UUID
    skill_id: UUID
    fork_id: UUID | None = Field(description="The fork it belongs to; null for the main line")
    number: int = Field(description="Its number within its line: main and each fork count from 1")
    source: SkillVersionSource
    previous: VersionRef | None = Field(
        description=(
            "What it was made after: the line's previous version, or for a fork's first "
            "version the main version the fork started from"
        )
    )
    restored_from: VersionRef | None = None
    proposal_id: UUID | None = Field(
        default=None, description="The skill change it applied, when it came from one"
    )
    created_by: PersonRef | None = None
    created_at: datetime


class VersionResourceSummary(BaseSchema):
    name: str
    description: str | None = None
    size_bytes: int
    digest: str = Field(
        description=(
            "The SHA-256 of the file's content: two versions name the same file with "
            "the same content exactly when their digests are equal"
        )
    )


class SkillVersionRead(SkillVersionSummary):
    description: str
    content: str
    resources: list[VersionResourceSummary] = Field(
        description="The files this version carries, without their contents"
    )


class SkillVersionList(BaseSchema):
    items: list[SkillVersionSummary]
    total: int


class VersionResourceRead(BaseSchema):
    name: str
    description: str | None = None
    content: str


class SkillVersionCreate(BaseSchema):
    """An edit of the text, saved as a new version on one line."""

    fork_id: UUID | None = Field(
        default=None, description="The fork to save it on; null saves it on the main line"
    )
    base_version_id: UUID = Field(
        description=(
            "The line's newest version as the editor read it. A line that moved since is "
            "refused rather than overwritten"
        )
    )
    description: str = Field(min_length=1, max_length=500)
    content: str


class SkillVersionRestore(BaseSchema):
    base_version_id: UUID = Field(
        description="The newest version of the restored version's line, as the person read it"
    )


class VersionNumberRef(BaseSchema):
    id: UUID
    number: int


class SkillForkRead(BaseSchema):
    """A fork as the skill page lists it."""

    id: UUID
    skill_id: UUID
    name: str
    base: VersionNumberRef = Field(description="The main version the fork started from")
    latest: VersionNumberRef | None = Field(
        description="Its newest own version; null while it has none and serves its base"
    )
    changes: int = Field(description="How many versions of its own it has")
    behind_main: int = Field(description="How many main versions came after its base")
    archive_candidate: bool = Field(
        description="No agent reads it and no run has served it for 30 days"
    )
    archived_at: datetime | None = None
    created_by: PersonRef | None = None
    created_at: datetime


class SkillForkList(BaseSchema):
    items: list[SkillForkRead]
    total: int


class SkillForkCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=64)
    from_version_id: UUID = Field(description="The main version the fork starts from")


class SkillForkUpdate(BaseSchema):
    name: str = Field(min_length=1, max_length=64)
