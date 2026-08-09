"""Schemas for agent exposures - where an agent is available."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models.agent_exposure import ExposureSurface
from app.schemas.base import BaseSchema


class ExposureTool(BaseSchema):
    """One channel lookup, as the binding's form offers it.

    Name and description come from the capability registry rather than being
    written again in the client. A tool's description is the sentence the model
    reads before deciding to call it, and the person deciding whether to grant
    it should be reading the same one - two paraphrases in two repositories is
    the shape of #144.
    """

    id: str
    name: str
    description: str


class ExposureRead(BaseSchema):
    """One place an agent is available, as the Builder shows it.

    Carries the bot's platform and name rather than only its id: the section is
    a list of places, and "Slack - Acme Support" is the place. Making the client
    join against a bot listing it may not be allowed to read would mean gating
    this section on `channels:manage`, which is not who publishes agents.
    """

    id: UUID
    agent_id: UUID
    surface: ExposureSurface
    channel_bot_id: UUID
    channel_bot_name: str
    environment_id: UUID | None = None
    session_scope: str | None = None
    # Read back, unlike a credential: it is instructions somebody wrote and has
    # to be able to edit, and the form that edits it needs its current value.
    prompt: str | None = None
    tools: list[str] = Field(
        default_factory=list,
        description="Channel lookups granted on this binding, by tool id",
    )
    available_tools: list[ExposureTool] = Field(
        default_factory=list,
        description=(
            "What this binding's platform can actually answer, so the form "
            "offers a checkbox only where there is something behind it. Telegram "
            "gives a bot no channel search and no way to read history, and a "
            "control whose only effect is a tool that says so is a worse answer "
            "than no control."
        ),
    )
    is_active: bool
    created_at: datetime | None = None


class ExposureList(BaseSchema):
    items: list[ExposureRead]
    total: int


class ExposureCreate(BaseSchema):
    channel_bot_id: UUID = Field(
        description=(
            "Which of the organization's bots this agent answers through. The "
            "surface is taken from the bot's platform rather than asked for - "
            "a bot is on exactly one platform, and accepting a second opinion "
            "about which would only create somewhere for the two to disagree."
        )
    )
    environment_id: UUID | None = Field(
        default=None,
        description=(
            "Which named environment answers here; omitted means the default. "
            "A dev bot bound to a dev environment serves the version it pins."
        ),
    )
    prompt: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "Added to the agent's instructions on this binding only - how to lay "
            "a message out here, how to give a link, how long an answer should "
            "be. Appended rather than substituted, so a surface can shape an "
            "answer and never contradict what the agent is for. Explicit null "
            "removes it."
        ),
    )
    session_scope: Literal["run", "conversation", "channel", "user", "agent"] | None = Field(
        default=None,
        description=(
            "How a workspace is shared *here*, overriding the agent's own default. "
            "Null leaves the spec deciding. This is where 'on this bot, one "
            "workspace per channel' belongs: the same agent in web chat and on "
            "Slack is one agent in two situations - one has an account and a "
            "conversation, the other a channel with threads in it."
        ),
    )


class ExposureUpdate(BaseSchema):
    tools: list[str] | None = Field(
        default=None,
        description=(
            "Which channel lookups this agent may make on this bot, by tool id - "
            "who is in the channel, what the channel is for, what was said in "
            "it. Per binding rather than per agent: the same agent on an "
            "internal Mattermost and a customer Slack has two different answers. "
            "Refused when the platform cannot answer the tool; an empty list "
            "grants none, which is what a new binding starts as."
        ),
    )
    is_active: bool | None = Field(
        default=None,
        description="Stop or resume answering here without losing who bound it, and when",
    )
    environment_id: UUID | None = Field(
        default=None,
        description="Rebind to another named environment; explicit null returns to the default",
    )
    prompt: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "Added to the agent's instructions on this binding only - how to lay "
            "a message out here, how to give a link, how long an answer should "
            "be. Appended rather than substituted, so a surface can shape an "
            "answer and never contradict what the agent is for. Explicit null "
            "removes it."
        ),
    )
    session_scope: Literal["run", "conversation", "channel", "user", "agent"] | None = Field(
        default=None,
        description=(
            "How a workspace is shared *here*, overriding the agent's own default. "
            "Null leaves the spec deciding. This is where 'on this bot, one "
            "workspace per channel' belongs: the same agent in web chat and on "
            "Slack is one agent in two situations - one has an account and a "
            "conversation, the other a channel with threads in it."
        ),
    )


class ExposureTarget(BaseSchema):
    """A bot an agent could be bound to.

    Deliberately three fields. A bot row also holds a sealed token, a webhook
    secret and an access policy, and none of that is any of the Builder's
    business - this endpoint exists so choosing where an agent is available does
    not require permission to reconfigure the bot itself.
    """

    id: UUID
    platform: ExposureSurface
    name: str
    is_active: bool


class ExposureTargetList(BaseSchema):
    items: list[ExposureTarget]
    total: int
