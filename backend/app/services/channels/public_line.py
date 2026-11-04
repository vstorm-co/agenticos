"""A line that answers people who never linked an account.

A WhatsApp bot can answer a customer in a private chat with no account of
theirs. That is one key in the bot's access policy, read here so the router, the
bot service and the console agree on what it means, and it comes with a rule the
rest of the platform holds a run to: such a run spends under a ceiling or not at
all.

The ceiling is the same pair of caps the runner checks before it opens a run with
no member behind it - the served agent's own monthly budget and the
organization's monthly cap. Whichever is set is enough; with neither, nothing
stops the spend.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.db.models.agent_exposure import AgentExposure
from app.db.models.channel_bot import ChannelBot
from app.repositories import (
    agent_environment_repo,
    agent_exposure_repo,
    agent_repo,
    organization_repo,
)

PLATFORMS_THAT_ANSWER_STRANGERS = frozenset({"whatsapp"})
"""Where a customer with no account can be answered at all.

A customer there is a number or a business-scoped id the platform vouches for, and the
platform's own terms are what make answering one reasonable. Everywhere else a chat
account with no linked person is asked to link.
"""


def parse_policy(stored: object) -> dict[str, Any]:
    """A bot's stored access policy as a dict, whether it was stored as one or as JSON text.

    Anything else - no policy, or a value that is not one - is no policy.
    """
    if isinstance(stored, str):
        return json.loads(stored) if stored else {}
    return dict(stored) if isinstance(stored, Mapping) else {}


def answers_unlinked_direct(policy: Mapping[str, Any]) -> bool:
    """Whether a private chat from somebody with no linked account is answered.

    True only when the switch is a real `True`, the mode is not `jwt_linked` and
    `require_link` is off. The second and third are the operator's way of saying a
    link is wanted, and they win: a policy that carries both is a policy that asks
    for a link. Read from the stored dict, so a string `"true"` or a policy saved
    before the key existed is a closed line.
    """
    return (
        policy.get("answer_unlinked_direct") is True
        and policy.get("mode") != "jwt_linked"
        and not bool(policy.get("require_link", False))
    )


def answers_unlinked_on(platform: str, stored_policy: object) -> bool:
    """Whether a bot of `platform` with this stored policy answers people with no account.

    The one reader the router and the bot service share: the policy as the row holds
    it, on a platform that can take it.
    """
    return platform in PLATFORMS_THAT_ANSWER_STRANGERS and answers_unlinked_direct(
        parse_policy(stored_policy)
    )


def bot_answers_unlinked_direct(bot: ChannelBot) -> bool:
    """Whether this bot answers a private chat from somebody with no linked account."""
    return answers_unlinked_on(bot.platform, bot.access_policy)


@dataclass(frozen=True)
class Ceiling:
    """What bounds the spend of a run with no member behind it."""

    agent_monthly_usd: Decimal | None
    organization_monthly_usd: Decimal | None

    @property
    def exists(self) -> bool:
        """Whether either cap is set."""
        return self.agent_monthly_usd is not None or self.organization_monthly_usd is not None


async def served_spec(db: AsyncSession, exposure: AgentExposure) -> AgentSpec | None:
    """The spec a binding answers with, or `None` when there is nothing published to answer.

    The environment the binding names decides the version, and with none named it is
    the agent's current one - the version a run on this binding would be resolved
    to. Read inside the binding's own organization and without a caller to check:
    this decides whether a line may be opened, not who may run the agent.
    """
    agent = await agent_repo.get(db, exposure.agent_id, organization_id=exposure.organization_id)
    if agent is None:
        return None
    version_id = agent.current_version_id
    if exposure.environment_id is not None:
        environment = await agent_environment_repo.get(
            db, exposure.environment_id, organization_id=exposure.organization_id
        )
        if environment is None or environment.agent_id != agent.id:
            return None
        version_id = environment.version_id
    if version_id is None:
        return None
    version = await agent_repo.get_version(db, version_id, organization_id=exposure.organization_id)
    return None if version is None else AgentSpec.model_validate(version.spec)


async def bot_served_spec(db: AsyncSession, bot_id: UUID) -> AgentSpec | None:
    """The spec of the agent a bot is bound to, active or paused, or `None` with no binding.

    A paused binding still counts: resuming it is a click away, so a line that
    answers strangers is judged against the agent it will answer with then.
    """
    binding = await agent_exposure_repo.bound_to_bot(db, channel_bot_id=bot_id)
    return None if binding is None else await served_spec(db, binding)


async def ceiling_for(
    db: AsyncSession, *, organization_id: UUID, spec: AgentSpec | None
) -> Ceiling:
    """The caps that would bound a run of `spec` in the organization."""
    organization = await organization_repo.get_by_id(db, organization_id)
    budget = None if spec is None or spec.budget is None else spec.budget.monthly_usd
    return Ceiling(
        agent_monthly_usd=None if budget is None else Decimal(str(budget)),
        organization_monthly_usd=None if organization is None else organization.monthly_budget_usd,
    )


async def refuse_without_ceiling(
    db: AsyncSession,
    *,
    organization_id: UUID,
    spec: AgentSpec | None,
    channel_bot_id: UUID | None,
) -> None:
    """Refuse when a line that answers strangers would spend with no ceiling.

    Raises:
        BadRequestError: When neither the agent's monthly budget nor the
            organization's monthly cap is set.
    """
    if (await ceiling_for(db, organization_id=organization_id, spec=spec)).exists:
        return
    raise BadRequestError(
        message=(
            "A bot that answers people who have not linked an account needs a spending limit. "
            "Give the agent it serves a monthly budget, or give the organization a monthly cap."
        ),
        details={"channel_bot_id": None if channel_bot_id is None else str(channel_bot_id)},
    )
