"""What the channel steps share: one of the organization's bots, reached as itself.

A step names a channel bot - Slack, Mattermost or Telegram - and acts through
the adapter the platform's inbound traffic already goes through, with the bot's
own token from the vault. So a message a workflow sends arrives as that bot, and
what a step can read is exactly what the bot may read on that platform.

A bot speaks for the whole organization, so using one takes `channels:manage`:
the graph's author must hold it to publish, and the run's principal on every
run, read afresh - a member who loses it stops the step with
`CHANNEL_NOT_USABLE`, as does a bot that was deleted or switched off.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_tools._directory import ChannelDirectoryUnsupported
from app.core.permissions import AuthContext, Perm
from app.db.models.channel_bot import ChannelBot
from app.db.session import get_worker_db_context
from app.repositories import channel_bot as channel_bot_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import ChannelAdapter
from app.services.workflow_execution import context
from app.workflows.contracts.results import Failed, NodeResult, WorkflowError

logger = logging.getLogger(__name__)

BOT_FIELD = Field(
    title="Bot",
    description="Which of the organization's channel bots this step acts as",
    json_schema_extra={"x-resource": "channel_bot"},
)


class ChannelBotConfig(BaseModel):
    """Which bot the step acts as."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bot_id: UUID = BOT_FIELD


def failed(code: str, message: str, **details: Any) -> Failed:
    return Failed(error=WorkflowError(code=code, message=message, details=details))


async def _usable_bot(db: AsyncSession, auth: AuthContext, bot_id: UUID) -> ChannelBot | None:
    if not auth.has(Perm.CHANNELS_MANAGE):
        return None
    bot = await channel_bot_repo.get_for_org(db, bot_id, organization_id=auth.organization_id)
    return bot if bot is not None and bot.is_active else None


async def check_bot(db: AsyncSession, ctx: AuthContext, config: BaseModel) -> list[tuple[str, str]]:
    """Refuse a bot the graph's author may not act as, or one that is gone or off."""
    if not isinstance(config, ChannelBotConfig) or await _usable_bot(db, ctx, config.bot_id):
        return []
    return [
        (
            "bot_id",
            "This is not an active bot you can act as - using one needs channels:manage",
        )
    ]


type BotCall = Callable[[ChannelAdapter, str, str | None], Awaitable[NodeResult]]
"""The step's own call: the platform's adapter, the bot's token, its server address."""


async def with_bot(config: ChannelBotConfig, call: BotCall) -> NodeResult:
    """Run `call` as the step's bot, or say why it cannot.

    The bot is re-read on every run against the run's principal. A platform that
    does not let a bot do what the step asks - Telegram reading a channel's
    history - fails with `CHANNEL_UNSUPPORTED` rather than an empty answer.
    """
    current = context.current()
    async with get_worker_db_context() as db:
        bot = await _usable_bot(db, current.auth, config.bot_id)
    if bot is None:
        return failed(
            "CHANNEL_NOT_USABLE",
            "The bot this step acts as is gone, switched off, or no longer yours to use",
        )
    adapter = get_adapter(bot.platform)
    try:
        return await call(adapter, unseal_bot_token(bot), bot.api_base_url)
    except ChannelDirectoryUnsupported as exc:
        return failed("CHANNEL_UNSUPPORTED", str(exc), platform=bot.platform)
    except Exception:
        # A platform's error can quote the request, and the request carries the token.
        logger.exception("workflow_channel_step_failed", extra={"platform": bot.platform})
        return Failed(
            error=WorkflowError(
                code="CHANNEL_CALL_FAILED",
                message=f"{bot.platform.capitalize()} did not answer",
                details={"platform": bot.platform},
                retryable=True,
            )
        )
