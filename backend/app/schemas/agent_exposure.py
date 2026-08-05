"""Schemas for agent exposures - where an agent is available."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models.agent_exposure import ExposureSurface
from app.schemas.base import BaseSchema


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
    is_active: bool | None = Field(
        default=None,
        description="Stop or resume answering here without losing who bound it, and when",
    )
    environment_id: UUID | None = Field(
        default=None,
        description="Rebind to another named environment; explicit null returns to the default",
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
