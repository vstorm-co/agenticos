"""Schemas for agent exposures — where an agent is available."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.db.models.agent_exposure import ExposureSurface
from app.schemas.base import BaseSchema


class ExposureRead(BaseSchema):
    """One place an agent is available, as the Builder shows it.

    Carries the bot's platform and name rather than only its id: the section is
    a list of places, and "Slack — Acme Support" is the place. Making the client
    join against a bot listing it may not be allowed to read would mean gating
    this section on ``channels:manage``, which is not who publishes agents.
    """

    id: UUID
    agent_id: UUID
    surface: ExposureSurface
    channel_bot_id: UUID
    channel_bot_name: str
    is_active: bool
    max_per_run_usd: Decimal | None = None
    monthly_usd: Decimal | None = None
    created_at: datetime | None = None


class ExposureList(BaseSchema):
    items: list[ExposureRead]
    total: int


class ExposureBudget(BaseSchema):
    """What one binding may spend, metered against its own runs.

    Two limits because they fail differently. A monthly cap stops a slow leak
    nobody is watching; only a per-run cap stops one adversarial prompt driving
    a loop, because a rate limiter counts requests and cannot see cost.

    Both optional on a channel binding, where the sender is a known member of
    the organization. They stop being optional on a surface open to anonymous
    visitors — a budget is the only thing standing between a public URL and
    somebody's card — and that surface will refuse an exposure without them.
    """

    max_per_run_usd: Decimal | None = Field(default=None, gt=0)
    monthly_usd: Decimal | None = Field(default=None, gt=0)


class ExposureCreate(ExposureBudget):
    channel_bot_id: UUID = Field(
        description=(
            "Which of the organization's bots this agent answers through. The "
            "surface is taken from the bot's platform rather than asked for — "
            "a bot is on exactly one platform, and accepting a second opinion "
            "about which would only create somewhere for the two to disagree."
        )
    )


class ExposureUpdate(ExposureBudget):
    is_active: bool | None = Field(
        default=None,
        description="Stop or resume answering here without losing who bound it, and when",
    )


class ExposureTarget(BaseSchema):
    """A bot an agent could be bound to.

    Deliberately three fields. A bot row also holds a sealed token, a webhook
    secret and an access policy, and none of that is any of the Builder's
    business — this endpoint exists so choosing where an agent is available does
    not require permission to reconfigure the bot itself.
    """

    id: UUID
    platform: ExposureSurface
    name: str
    is_active: bool


class ExposureTargetList(BaseSchema):
    items: list[ExposureTarget]
    total: int
