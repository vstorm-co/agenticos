"""Schemas for published artifacts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

ArtifactMediaTypeLiteral = Literal["text/html", "text/markdown"]


class ArtifactVersionRead(BaseSchema):
    id: UUID
    number: int
    media_type: ArtifactMediaTypeLiteral
    size_bytes: int
    run_id: UUID | None = Field(
        default=None, description="The run that published it, while that run is still kept"
    )
    created_at: datetime


class ArtifactVersionList(BaseSchema):
    items: list[ArtifactVersionRead]
    total: int


class ArtifactRead(BaseSchema):
    id: UUID
    name: str = Field(description="The handle the agent republishes it by; unique per agent")
    title: str
    visibility: str
    owner_user_id: UUID | None = None
    agent_id: UUID | None = Field(
        default=None, description="The agent whose runs publish it; null once that agent is gone"
    )
    public_url: str | None = Field(
        default=None,
        description="The 'anyone with the link' address, when one is on. Unguessable, revocable",
    )
    published_at: datetime
    current_version: ArtifactVersionRead | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ArtifactDetail(ArtifactRead):
    """One artifact as its own page reads it, with what the caller may do to it."""

    can_edit: bool = Field(
        description=(
            "Whether the caller may retitle, share, link or delete it - the role scope "
            "and any grant on this artifact, decided by the server"
        )
    )


class ArtifactList(BaseSchema):
    items: list[ArtifactRead]
    total: int


class ArtifactUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class ArtifactView(BaseSchema):
    """Where a frame loads one version from, and until when that address holds."""

    url: str = Field(description="Signed, short-lived; served under a sandbox policy")
    expires_at: datetime
    version: ArtifactVersionRead


class PublicArtifactRead(BaseSchema):
    """What a stranger holding the link learns: the page, and nothing about who made it."""

    title: str
    published_at: datetime
    view: ArtifactView
