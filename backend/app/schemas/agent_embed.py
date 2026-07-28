"""Schemas for agent embeds - the widget an agent is published as."""

from typing import Literal
from uuid import UUID

from pydantic import Field, HttpUrl, field_validator

from app.schemas.base import BaseSchema, TimestampSchema

AuthMode = Literal["public", "jwt"]


class EmbedTheme(BaseSchema):
    """What a widget looks like, as far as it is configurable.

    A fixed set of fields rather than a stylesheet: this markup runs on somebody
    else's page, and free-form CSS in a JSONB column is a stylesheet nobody
    reviews shipped to a third party's browser.
    """

    title: str = Field(default="Ask us anything", max_length=80)
    subtitle: str = Field(default="", max_length=120)
    greeting: str = Field(default="Hi - what can I help you with?", max_length=400)
    placeholder: str = Field(default="Type your message…", max_length=80)
    accent: str = Field(default="#4f46e5", pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    position: Literal["left", "right"] = "right"
    launcher_label: str = Field(default="Chat", max_length=24)


class EmbedCreate(BaseSchema):
    """Publish one agent as a widget."""

    agent_id: UUID
    name: str = Field(min_length=1, max_length=128)
    auth_mode: AuthMode = "public"
    # Required in `jwt` mode and refused in `public` mode; the service enforces
    # both, because a secret stored where nothing reads it is a secret somebody
    # believes is protecting them.
    jwt_secret: str | None = Field(default=None, min_length=16, max_length=512)
    allowed_origins: list[HttpUrl] = Field(
        default_factory=list,
        max_length=20,
        description="Sites this widget may be opened from. Empty means nowhere.",
    )
    theme: EmbedTheme = Field(default_factory=EmbedTheme)
    context: str | None = Field(default=None, max_length=2000)
    rate_limit_per_minute: int = Field(default=10, ge=1, le=120)


class EmbedUpdate(BaseSchema):
    """Everything an embed may change after it exists.

    The agent is not here on purpose: repointing a live widget at a different
    agent silently changes what a customer's visitors are talking to. Delete it
    and publish a new one, which leaves a trail.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    auth_mode: AuthMode | None = None
    jwt_secret: str | None = Field(default=None, min_length=16, max_length=512)
    allowed_origins: list[HttpUrl] | None = Field(default=None, max_length=20)
    theme: EmbedTheme | None = None
    context: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=120)


class EmbedRead(BaseSchema, TimestampSchema):
    """One widget, as its owner sees it.

    `jwt_secret` is absent by construction: it is written once and never read
    back, like every other credential this platform stores.
    """

    id: UUID
    agent_id: UUID
    name: str
    public_key: str
    auth_mode: AuthMode
    has_jwt_secret: bool
    allowed_origins: list[str]
    theme: EmbedTheme
    context: str | None
    is_active: bool
    rate_limit_per_minute: int
    # Ready to paste. Assembled server-side so the one place that knows the
    # public URL is the deployment's own configuration.
    snippet: str


class EmbedList(BaseSchema):
    items: list[EmbedRead]
    total: int


class PublicEmbedConfig(BaseSchema):
    """What the widget itself is told, before anybody has authenticated.

    Deliberately thin. It is served to any origin on the allow-list and is
    therefore public: a name, a look, and whether a token will be demanded. No
    agent id, no organization, no counts.
    """

    title: str
    subtitle: str
    greeting: str
    placeholder: str
    accent: str
    position: Literal["left", "right"]
    launcher_label: str
    requires_token: bool
    agent_name: str

    @field_validator("agent_name")
    @classmethod
    def _no_empty_name(cls, value: str) -> str:
        return value or "Assistant"
