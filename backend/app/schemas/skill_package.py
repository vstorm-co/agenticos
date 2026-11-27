"""A standalone skill package preview contains metadata, never resource bodies."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from app.core.skill_files import ResourceEncoding, SkillMarkdown
from app.schemas.base import BaseSchema


class SkillPackageFile(BaseSchema):
    name: str
    size_bytes: int
    sha256: str
    encoding: ResourceEncoding


class SkillPackagePreview(BaseSchema):
    name: str
    description: str
    category: str | None
    content: SkillMarkdown
    manifest_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    fingerprint: str
    files: list[SkillPackageFile]
    total_bytes: int
    max_file_bytes: int
    max_package_bytes: int
    max_files: int
    execution: Literal["none"] = "none"


class SkillPackageApplied(BaseSchema):
    skill_id: UUID
    version_id: UUID
    name: str
    files: int
    fingerprint: str
