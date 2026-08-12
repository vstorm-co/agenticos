"""Schemas for agent embeds - the public surfaces one agent is published on.

Three of them, and the *kind* is what tells them apart: a widget pasted into
somebody else's site, a raw socket somebody writes their own client against, and
a page we serve ourselves at a link. They share a public key, a rate bucket, a
budget and a pause switch, and they differ in what there is to configure - which
is why `config` is one discriminated union rather than three columns with two of
them inert on every row.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, HttpUrl, field_validator

from app.schemas.base import BaseSchema, TimestampSchema

AuthMode = Literal["public", "jwt"]

EmbedKind = Literal["widget", "socket", "page"]
"""Which surface an embed is.

Fixed at creation and never changed afterwards, for the reason the agent is not
changeable either: every tag already pasted, every client already written and
every link already sent names this row, and turning a widget into a page would
change what all three do without touching any of them.
"""


class WidgetConfig(BaseSchema):
    """What the bubble in the corner of somebody else's page looks like.

    A fixed set of fields rather than a stylesheet: this markup runs on somebody
    else's page, and free-form CSS in a JSONB column is a stylesheet nobody
    reviews shipped to a third party's browser.
    """

    kind: Literal["widget"] = "widget"
    title: str = Field(default="Ask us anything", max_length=80)
    subtitle: str = Field(default="", max_length=120)
    greeting: str = Field(default="Hi - what can I help you with?", max_length=400)
    placeholder: str = Field(default="Type your message…", max_length=80)
    accent: str = Field(default="#4f46e5", pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    position: Literal["left", "right"] = "right"
    launcher_label: str = Field(default="Chat", max_length=24)


class SocketConfig(BaseSchema):
    """A client of one's own, and so nothing here to style.

    Empty on purpose rather than absent. Whoever connects to the socket renders
    the conversation themselves - a mobile app, a kiosk, a component in their own
    design system - so a colour or a launcher label would be a field we store and
    nobody reads. What this kind *does* carry is the shared configuration every
    embed has: the origin allow-list its handshake is checked against, its auth
    mode, its context and its rate limit.
    """

    kind: Literal["socket"] = "socket"


HostedLogo = Literal["agent", "organization", "none"]


class PageConfig(BaseSchema):
    """What a page we serve ourselves is branded with.

    A fixed set of fields, for the same reason `WidgetConfig` is one: this
    renders to the public internet, and free-form styling in a JSONB column is a
    stylesheet nobody reviews.

    Its own model rather than more fields on `WidgetConfig`, because the two
    surfaces do not describe the same thing: a launcher label and a corner to sit
    in mean nothing on a full page, and a page needs a browser-tab title a bubble
    has no use for.
    """

    kind: Literal["page"] = "page"
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


EmbedConfig = Annotated[WidgetConfig | SocketConfig | PageConfig, Field(discriminator="kind")]
"""The half of an embed that depends on which surface it is.

Tagged by `kind` inside the object rather than beside it, so there is one place
a client says which surface it means and one place the server reads it back. The
`agent_embeds.kind` column is that tag projected out, because a `CHECK` cannot
usefully read a JSONB key and neither can an index.
"""


class EmbedVariable(BaseSchema):
    """One thing the integration must tell this embed about the visitor.

    A name and a promise, and nothing about *where* the value comes from - the
    widget reads `window.AgenticOSContext`, a page reads its own URL, and a
    declaration that also named a source would be a second place for those to
    disagree.
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
            "Whether a page may take this value from `?var_<name>=` in its own "
            "URL. Off by default and deliberately per variable: a query "
            "parameter is visitor-controlled input, so `user_tier=premium` typed "
            "into the address bar has to be impossible unless somebody decided "
            "otherwise for that one variable. It has no meaning on a widget or a "
            "socket, where the value arrives from an integration the operator "
            "controls."
        ),
    )


class EmbedCreate(BaseSchema):
    """Publish one agent on one public surface."""

    agent_id: UUID
    name: str = Field(min_length=1, max_length=128)
    config: EmbedConfig = Field(
        description=(
            "Which surface this is, and what it looks like. The `kind` inside it "
            "is fixed at creation - see `EmbedKind`."
        )
    )
    auth_mode: AuthMode = "public"
    # Required in `jwt` mode and refused in `public` mode; the service enforces
    # both, because a secret stored where nothing reads it is a secret somebody
    # believes is protecting them.
    jwt_secret: str | None = Field(default=None, min_length=16, max_length=512)
    allowed_origins: list[HttpUrl] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Sites a widget may be opened from, or a socket handshake may report. "
            "Required for both and refused on a page, which is served from this "
            "deployment's own origin and nowhere else."
        ),
    )
    context: str | None = Field(default=None, max_length=2000)
    context_variables: list[EmbedVariable] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "What the integration must tell this embed about the visitor in front "
            "of it. Appended to the agent's instructions as a marked block of "
            "data - values arrive from a browser, so they are never instructions."
        ),
    )
    rate_limit_per_minute: int = Field(default=10, ge=1, le=120)


class EmbedUpdate(BaseSchema):
    """Everything an embed may change after it exists.

    Two things are not here on purpose. The agent, because repointing a live
    surface at a different one silently changes what a customer's visitors are
    talking to. And the *kind*, because a tag, a client and a link already exist
    naming this key - `config` may be edited, but a config of a different kind is
    refused rather than migrating the row underneath them. Delete it and publish
    a new one, which leaves a trail.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: EmbedConfig | None = None
    auth_mode: AuthMode | None = None
    jwt_secret: str | None = Field(default=None, min_length=16, max_length=512)
    allowed_origins: list[HttpUrl] | None = Field(default=None, max_length=20)
    context: str | None = Field(default=None, max_length=2000)
    context_variables: list[EmbedVariable] | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=120)


class EmbedRead(BaseSchema, TimestampSchema):
    """One published surface, as its owner sees it.

    `jwt_secret` is absent by construction: it is written once and never read
    back, like every other credential this platform stores.

    The three integration strings are `None` on the kinds they do not belong to,
    rather than assembled for every row and filtered by whoever renders them: a
    script tag for a socket integration is a line somebody would paste.
    """

    id: UUID
    agent_id: UUID
    name: str
    kind: EmbedKind
    config: EmbedConfig
    public_key: str
    auth_mode: AuthMode
    has_jwt_secret: bool
    allowed_origins: list[str]
    context: str | None
    context_variables: list[EmbedVariable] = []
    is_active: bool
    rate_limit_per_minute: int
    # Ready to paste, on a widget. Assembled server-side so the one place that
    # knows the public URL is the deployment's own configuration.
    snippet: str | None
    # The socket, on a widget and on a socket integration: the widget speaks this
    # protocol, so its own row publishing the URL is what makes "write your own
    # client instead" a step rather than a rewrite. Carries no token - see
    # `socket_url_for`.
    socket_url: str | None
    # The link, on a page. Off the frontend's base URL, because the page is
    # served by the frontend.
    page_url: str | None


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


class PublicPageConfig(BaseSchema):
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
