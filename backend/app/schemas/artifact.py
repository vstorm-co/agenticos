"""Schemas for published artifacts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field

from app.schemas.base import BaseSchema
from app.schemas.virtual_table import ColumnTypeName

ArtifactMediaTypeLiteral = Literal["text/html", "text/markdown"]


class BindingRequest(BaseSchema):
    """A live-data binding as the model asks for it, before resolution."""

    model_config = ConfigDict(extra="forbid")

    view: UUID
    fields: dict[str, str] = Field(
        description="Field name to the table column it reads, given as a column id or a label"
    )


class ArtifactBinding(BaseSchema):
    """A binding as stored on a version, after its names were resolved to ids."""

    name: str
    view_id: UUID
    table_id: UUID
    fields: dict[str, UUID]
    status: Literal["ok", "unavailable"] = "ok"
    reason: str | None = None


class ArtifactBindingRead(BaseSchema):
    """A binding as an API client sees it: field names only, no column ids."""

    name: str
    view_id: UUID
    table_id: UUID
    fields: list[str]
    status: Literal["ok", "unavailable"] = "ok"
    reason: str | None = None


class BoundField(BaseSchema):
    """What one field of a binding reads now: its column's current label and type."""

    label: str = Field(description="The column's label now; the field name for a missing column")
    type: ColumnTypeName = Field(description="The column's type now; `text` for a missing column")
    options: list[str] | None = Field(
        default=None, description="A select column's live choices, by label"
    )
    state: Literal["ok", "archived", "missing"] = Field(
        description="`archived` or `missing` when the column no longer serves values"
    )


class BindingData(BaseSchema):
    """One binding's records for a page load, read with the viewer's own access."""

    status: Literal["ok", "unavailable"]
    reason: str | None = Field(
        default=None,
        description="Why the binding is unavailable. Only for a viewer who may edit the page",
    )
    truncated: bool = Field(description="Whether a limit left records out")
    limit: Literal["records", "bytes"] | None = Field(
        default=None, description="Which limit left records out"
    )
    count: int = Field(description="How many records are served, not how many the view matches")
    filters_dropped: bool = Field(
        description="Whether a filter of the view named a column no longer live, so it matches more"
    )
    fields: dict[str, BoundField]
    # Any: a cell is a string, number, boolean, list or link list, by its column's type.
    records: list[dict[str, Any]] = Field(
        description="Each record as its `id` and every named field, `null` when empty"
    )


class ArtifactData(BaseSchema):
    """A page version's live data: every binding, each read as the viewer."""

    bindings: dict[str, BindingData]
    read_at: datetime


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
    live: bool = Field(
        default=False, description="Whether the current version reads live data through bindings"
    )
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
    bindings: list[ArtifactBindingRead] = Field(
        default_factory=list,
        description=(
            "The current version's bindings, each with its status and, when unavailable, "
            "why. Only for a caller who may edit it; empty otherwise"
        ),
    )


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

    # Aware, so a datetime sent without an offset is refused at the door instead
    # of failing the comparison with now() as a 500.
    expires_at: AwareDatetime | None = Field(
        default=None,
        description="When the link stops opening anything; in the future, with a UTC offset",
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
    nonce: str = Field(description="What the page and the console match their messages on")
    live: bool = Field(description="Whether the page asks the console for its bindings' data")


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
