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


HostedLogo = Literal["agent", "organization", "none"]


class HostedConfig(BaseSchema):
    """What a hosted page is branded with.

    A fixed set of fields, for the same reason `EmbedTheme` is one: this renders
    to the public internet, and free-form styling in a JSONB column is a
    stylesheet nobody reviews.

    Its own model rather than more fields on `EmbedTheme`, because the two
    surfaces do not describe the same thing: a launcher label and a corner to sit
    in mean nothing on a full page, and a page needs a browser-tab title a bubble
    has no use for.
    """

    title: str = Field(
        default="",
        max_length=80,
        description="The page and browser-tab title. Empty falls back to the agent's name.",
    )
    welcome: str = Field(
        default="",
        max_length=600,
        description=(
            "Shown above the composer before the first question. It is rendered "
            "to the visitor and never sent to the model - a greeting in the "
            "model's history is a turn the agent thinks it took."
        ),
    )
    accent: str = Field(default="#4f46e5", pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    logo: HostedLogo = Field(
        default="agent",
        description=(
            "Which image the page shows: the agent's avatar, the organization's, "
            "or none. A choice among images this platform already stores rather "
            "than a URL or a second upload path - an operator-supplied URL is a "
            "third-party request from a page we serve, and one more thing to "
            "make safe."
        ),
    )


class EmbedVariable(BaseSchema):
    """One thing the page must tell this widget about the visitor.

    A name and a promise, and nothing about *where* the value comes from - the
    widget reads `window.AgenticOSContext`, and a declaration that also named a
    source would be a second place for the two to disagree.
    """

    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        description=(
            "The key the page supplies, e.g. `plan`. Lower case, digits and "
            "underscores - it is written into a prompt and read back by a "
            "person, not evaluated."
        ),
    )
    required: bool = Field(
        default=False,
        description=(
            "Whether the agent is expected to have it. A missing required value "
            "omits its line and is logged rather than refusing the turn: a "
            "visitor must not lose an answer because an integrator forgot a key."
        ),
    )
    description: str = Field(
        default="",
        max_length=200,
        description="What it is for, shown to whoever writes the integration",
    )
    url_safe: bool = Field(
        default=False,
        description=(
            "Whether a hosted page may take this value from `?var_<name>=` in its "
            "own URL. Off by default and deliberately per variable: a query "
            "parameter is visitor-controlled input, so `user_tier=premium` typed "
            "into the address bar has to be impossible unless somebody decided "
            "otherwise for that one variable. It has no meaning in the widget, "
            "which reads `window.AgenticOSContext` from a page the operator "
            "controls."
        ),
    )


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
    hosted: bool = Field(
        default=False,
        description=(
            "Also serve this embed as a page of our own, at `/e/<public_key>`. "
            "Refused in `jwt` mode, and refused when a required variable is not "
            "marked URL-safe - both at creation, with a message."
        ),
    )
    hosted_config: HostedConfig = Field(default_factory=HostedConfig)
    context: str | None = Field(default=None, max_length=2000)
    context_variables: list[EmbedVariable] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "What the page must tell this widget about the visitor in front of "
            "it. Appended to the agent's instructions as a marked block of data "
            "- values arrive from a browser, so they are never instructions."
        ),
    )
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
    hosted: bool | None = None
    hosted_config: HostedConfig | None = None
    context: str | None = Field(default=None, max_length=2000)
    context_variables: list[EmbedVariable] | None = Field(default=None, max_length=20)
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
    hosted: bool
    hosted_config: HostedConfig
    context: str | None
    context_variables: list[EmbedVariable] = []
    is_active: bool
    rate_limit_per_minute: int
    # Ready to paste. Assembled server-side so the one place that knows the
    # public URL is the deployment's own configuration.
    snippet: str
    # The other integration: the socket, for somebody writing their own client
    # rather than pasting a tag into a site they do not control. Same reason it
    # is assembled server-side, and it carries no token - see `socket_url_for`.
    socket_url: str
    # The link, when hosting is on; `None` when it is off, so a panel has nothing
    # to show rather than a URL that answers 404.
    hosted_url: str | None


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


class PublicHostedConfig(BaseSchema):
    """What a hosted page renders itself from, before anybody says anything.

    Thin for the same reason `PublicEmbedConfig` is: served to whoever has the
    link, so a name, a look and what the page may ask for - no agent id, no
    organization, no counts.

    `variables` is the declared set a visitor's URL may fill, and only the ones
    marked URL-safe reach it. The page needs the list to know which `?var_…`
    parameters to forward; the server drops anything else regardless, so this is
    a convenience rather than the enforcement.
    """

    title: str
    welcome: str
    accent: str
    logo_url: str | None
    agent_name: str
    variables: list[str] = []
