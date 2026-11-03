"""Who continues a parked chat run, and what a chat is told when one ends (#2656).

A run started in Slack, Telegram, Mattermost, Teams or Discord can be decided
somewhere else: the console, the web chat, the session API. The run then belongs
to the chat it was asked in, and that chat hears about the outcome. This module
holds the one predicate that says so, the fixed sentences a chat is told when a
run ends without an answer, and the plain post that carries them.

A notice is never built from a refusal message or from run data. The four
sentences below are the whole vocabulary; a chat room is not a place to explain
who was refused or why.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from pydantic import ValidationError

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.permissions import AuthContext
from app.db.models.agent_run import CHANNEL_SURFACES, AgentRun
from app.db.session import get_db_context
from app.repositories import channel_bot as channel_bot_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter, register_adapter
from app.services.channels.base import OutgoingMessage

logger = logging.getLogger(__name__)

EXPIRED_NOTICE: Final = "This request expired without a decision."
STOPPED_NOTICE: Final = "This run was stopped from the console."
STRANDED_NOTICE: Final = "A decision was recorded, but the run could not continue."
REFUSED_NOTICE: Final = "That was decided outside the chat, but the run could not continue."

_SURFACE_VALUES = frozenset(surface.value for surface in CHANNEL_SURFACES)


def chat_destination(run: AgentRun) -> ChannelDestination | None:
    """The chat a parked channel run came from, or None when it has none.

    Only `paused_state.channel_destination` counts. A run parked with no adapter
    holds an explicit null, one parked before the destination was recorded has no
    key, and a value that no longer validates is logged and read as absent: all
    three continue nowhere.
    """
    if run.surface not in _SURFACE_VALUES:
        return None
    state = run.paused_state
    if not isinstance(state, dict):
        return None
    stored = state.get("channel_destination")
    if stored is None:
        return None
    try:
        return ChannelDestination.model_validate(stored)
    except ValidationError:
        logger.warning("channel_destination_unreadable run_id=%s", run.id)
        return None


def decided_by_a_person(ctx: AuthContext) -> bool:
    """A person signed in decided, not an API key and not nobody."""
    return ctx.api_key_id is None and ctx.user_id is not None


def continues_in_chat(run: AgentRun, decider: AuthContext) -> bool:
    """Whether a decision on this run is continued in the chat it was asked in.

    True when the run is on a channel surface, its chat is recorded, and a person
    decided. A key's decision is recorded but never continues a run a person
    started.
    """
    return chat_destination(run) is not None and decided_by_a_person(decider)


@dataclass(frozen=True)
class ChatNotice:
    """One fixed sentence for one chat: ids, the recorded destination and the text."""

    organization_id: UUID
    run_id: UUID
    destination: ChannelDestination
    text: str


async def post_notices(notices: Sequence[ChatNotice]) -> None:
    """Post each notice in turn, so a backlog never opens more than one connection.

    A sweep that ends many runs queues one of these rather than one task per run:
    spawned tasks all start at once, and each would hold a pooled database
    connection while its platform answers. It never raises, and a chat that cannot
    be told does not stop the next one.
    """
    for notice in notices:
        await _post_one(notice)


async def post_notice(
    *, organization_id: UUID, run_id: UUID, destination: ChannelDestination, text: str
) -> None:
    """Post one fixed sentence to the chat, with the bot's current credential.

    Opens its own session, so it is safe to spawn after commit. It never raises:
    a chat that cannot be told is logged by run and bot id, never by chat id or
    text.
    """
    await post_notices(
        [
            ChatNotice(
                organization_id=organization_id, run_id=run_id, destination=destination, text=text
            )
        ]
    )


async def _post_one(notice: ChatNotice) -> None:
    bot_id = notice.destination.bot_id
    try:
        # The session ends before the platform is called: a slow platform must never
        # hold a database connection.
        async with get_db_context() as db:
            bot = await channel_bot_repo.get_for_org(
                db, bot_id, organization_id=notice.organization_id
            )
            if bot is None or not bot.is_active:
                return
            adapter = get_adapter(bot.platform)
            token = unseal_bot_token(bot)
            message = OutgoingMessage(
                platform_chat_id=notice.destination.platform_chat_id,
                text=notice.text,
                api_base_url=bot.api_base_url,
            )
        await adapter.send_message(token, message)
    except KeyError:
        logger.warning("chat_notice_no_adapter run_id=%s bot_id=%s", notice.run_id, bot_id)
    except Exception as exc:
        logger.warning(
            "chat_notice_failed run_id=%s bot_id=%s error=%s",
            notice.run_id,
            bot_id,
            type(exc).__name__,
        )


def ensure_channel_adapters() -> None:
    """Register the chat adapters this process lacks, starting nothing.

    The API registers them at startup; the job worker never does, and a notice
    posted from a sweep still has to reach the chat. Idempotent. No polling loop
    and no stream: a send needs neither.
    """
    from app.services.channels.discord import DiscordAdapter
    from app.services.channels.mattermost import MattermostAdapter
    from app.services.channels.slack import SlackAdapter
    from app.services.channels.teams import teams_adapter
    from app.services.channels.telegram import TelegramAdapter

    for adapter_class in (SlackAdapter, TelegramAdapter, MattermostAdapter, DiscordAdapter):
        try:
            get_adapter(adapter_class.platform)
        except KeyError:
            register_adapter(adapter_class())
    teams_adapter()
