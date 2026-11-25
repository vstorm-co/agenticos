"""Owned, credential-free payloads carried by resource definitions."""

from collections.abc import Mapping
from typing import Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.agents.model_resolver import ModelApi, ModelRegion
from app.schemas.context import ContextModeLiteral
from app.schemas.skill import SkillResourceUpdate, SkillUpdate


def portable_connection_settings(
    url: str | None, params: Mapping[str, JsonValue] | None = None
) -> bool:
    """Opaque URL parameters and transport headers can carry credentials.

    Their meaning is server-specific. Do not guess which query/header values are
    safe, or strip them and pretend the resulting connection is equivalent.
    Such resources travel as references and need destination configuration.
    """
    try:
        endpoint = urlsplit(url or "")
    except ValueError:
        return False
    return (
        endpoint.username is None
        and endpoint.password is None
        and not endpoint.query
        and not endpoint.fragment
        and not (params and params.get("extra_headers"))
    )


class ContextContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    content: str
    format: str = Field(default="md", min_length=1, max_length=16)
    mode: ContextModeLiteral = "inject"


class SkillFileContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    content: str


class SkillContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    name: str = Field(min_length=1, max_length=64)
    description: str
    content: str
    category: str | None = Field(default=None, max_length=64)
    files: tuple[SkillFileContent, ...] = Field(default=(), max_length=10_000)


class SkillSnapshotContent(SkillContent):
    skill_id: UUID = Field(json_schema_extra={"x-resource": "skill"})
    number: int = Field(ge=1)


class ModelContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, allow_inf_nan=False)

    label: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=255)
    secret_id: UUID | None = Field(default=None, json_schema_extra={"x-resource": "secret"})
    base_url: str | None = Field(default=None, max_length=512)
    api: ModelApi | None = None
    region: ModelRegion | None = None
    params: dict[str, JsonValue] = Field(default_factory=dict)
    fallback_profile_ids: list[UUID] = Field(
        default_factory=list, json_schema_extra={"x-resource": "model_profile"}
    )

    @model_validator(mode="after")
    def connection_fields(self) -> Self:
        if not portable_connection_settings(self.base_url, self.params):
            raise ValueError(
                "Configure connection URLs and transport headers at the destination; do not put them in a portable model definition"
            )
        return self


class McpContent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    name: str = Field(min_length=1, max_length=32)
    label: str | None = Field(default=None, max_length=64)
    url: str = Field(min_length=1, max_length=2048)
    allowed_tools: list[str] | None = None
    include_instructions: bool = False
    trust_read_only_hints: bool = False
    catalog_key: str | None = None

    @field_validator("url")
    @classmethod
    def connection_url(cls, value: str) -> str:
        if not portable_connection_settings(value):
            raise ValueError(
                "Configure URL parameters at the destination; do not put them in a portable MCP definition"
            )
        return value


class ImportedSkillUpdate(SkillUpdate):
    """An existing snapshot's exact text must survive the usual form normalization."""

    model_config = ConfigDict(str_strip_whitespace=False)


class ImportedSkillResourceUpdate(SkillResourceUpdate):
    model_config = ConfigDict(str_strip_whitespace=False)
