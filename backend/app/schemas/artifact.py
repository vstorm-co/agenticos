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
    name: str = Field(
        description="The handle the agent republishes it by; unique per agent and environment"
    )
    title: str
    visibility: str
    owner_user_id: UUID | None = None
    agent_id: UUID | None = Field(
        default=None, description="The agent whose runs publish it; null once that agent is gone"
    )
    environment_id: UUID | None = Field(
        default=None,
        description="The named environment whose runs publish it; null for the default one",
    )
    environment_name: str | None = Field(
        default=None, description="That environment's name, while it exists"
    )
    public_url: str | None = Field(
        default=None,
        description="The 'anyone with the link' address, when one is on. Unguessable, revocable",
    )
    published_at: datetime
    current_version: ArtifactVersionRead | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ArtifactPublicLinkRead(BaseSchema):
    """The public link's settings, which hold whether or not the link is on."""

    expires_at: datetime | None = Field(
        default=None, description="After this, the link opens nothing"
    )
    pinned_version_id: UUID | None = Field(
        default=None, description="The version the link shows instead of the newest one"
    )
    pinned_version: int | None = Field(default=None, description="That version's number")
    password_protected: bool = Field(
        description="Whether a visitor must give a password before the page is shown"
    )
    view_count: int = Field(description="How many times the public link was opened")
    last_viewed_at: datetime | None = None
    embed_origins: list[str] = Field(
        description="The sites allowed to frame the public page, as `https://host` origins"
    )
    embed_url: str | None = Field(
        default=None,
        description="The address to put in another site's `<iframe>`, while the link is on",
    )


class ArtifactDetail(ArtifactRead):
    """One artifact as its own page reads it, with what the caller may do to it."""

    can_edit: bool = Field(
        description=(
            "Whether the caller may retitle, share, link, restore or delete it - the role "
            "scope and any grant on this artifact, decided by the server"
        )
    )
    public_link: ArtifactPublicLinkRead


class ArtifactList(BaseSchema):
    items: list[ArtifactRead]
    total: int


class ArtifactAgent(BaseSchema):
    """An agent behind at least one artifact the caller may open."""

    id: UUID
    name: str


class ArtifactAgentList(BaseSchema):
    items: list[ArtifactAgent]


class ArtifactUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class ArtifactPublicLinkUpdate(BaseSchema):
    """Change the public link's settings. A field left out is left as it is.

    `null` clears `expires_at`, `pinned_version_id` and `password`.
    """

    expires_at: datetime | None = Field(
        default=None, description="When the link stops opening anything; in the future"
    )
    pinned_version_id: UUID | None = Field(
        default=None, description="A kept version the link shows instead of the newest one"
    )
    password: str | None = Field(
        default=None,
        min_length=6,
        max_length=128,
        description="What a visitor must type first. Stored hashed; never returned",
    )
    embed_origins: list[str] | None = Field(
        default=None,
        max_length=20,
        description=(
            "The sites allowed to frame the public page - `https://intranet.example.com`, "
            "or `https://*.example.com` for its subdomains. Scheme and host only"
        ),
    )


class ArtifactView(BaseSchema):
    """Where a frame loads one version from, and until when that address holds."""

    url: str = Field(description="Signed, short-lived; served under a sandbox policy")
    expires_at: datetime
    version: ArtifactVersionRead


class PublicArtifactRead(BaseSchema):
    """What a stranger holding the link learns: the page, and nothing about who made it.

    Behind a password, nothing at all until the password is given: `password_required`
    is true and the other fields are empty.
    """

    password_required: bool = False
    title: str | None = None
    published_at: datetime | None = None
    view: ArtifactView | None = None


class PublicArtifactUnlock(BaseSchema):
    password: str = Field(min_length=1, max_length=128)
