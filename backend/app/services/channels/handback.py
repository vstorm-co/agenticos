"""Who continues a parked chat run, and what a chat is told when one ends (#2656).

A run started in Slack, Telegram, Mattermost, Teams or Discord can be decided
somewhere else: the console, the web chat, the session API. The run then belongs
to the chat it was asked in, and that chat hears about the outcome. This module
holds the one predicate that says so, the fixed sentences a chat is told when a
run ends without an answer, and the plain post that carries them.

A notice is never built from a refusal message or from run data. The four
sentences below are the whole vocabulary, plus the one reminder built by
`question_nudge_notice`, which carries only the hours left on the question;
a chat room is not a place to explain who was refused or why.
"""

import logging
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from pydantic import ValidationError

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.permissions import AuthContext
from app.db.models.agent_run import CHANNEL_SURFACES, AgentRun
from app.db.session import get_db_context
from app.repositories import agent_run_repo
from app.repositories import channel_bot as channel_bot_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter, register_adapter
from app.services.channels.base import OutgoingMessage

logger = logging.getLogger(__name__)

EXPIRED_NOTICE: Final = "This request expired without a decision."
STOPPED_NOTICE: Final = "This run was stopped from the console."
STRANDED_NOTICE: Final = "A decision was recorded, but the run could not continue."
REFUSED_NOTICE: Final = "That was decided outside the chat, but the run could not continue."


def question_nudge_notice(remaining_hours: int) -> str:
    """The one reminder that an `ask_user` question is still unanswered.

    Built, not constant, for the one number it carries: the hours left
    before the question expires. Everything else is fixed, like the
    sentences above - a chat room is not a place to paste the question in
    again, and the card in the conversation already holds it.
    """
    return f"Still waiting for your answer — the question expires in about {remaining_hours}h."


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


async def send_notice(notice: ChatNotice) -> None:
    """Send with fresh credentials; transport failures escape for durable retries."""
    from app.services.channels.next_steps import incoming_for_run
    from app.services.channels.router import ChannelMessageRouter

    bot_id = notice.destination.bot_id
    # The session ends before the platform is called: a slow platform must never
    # hold a database connection.
    async with get_db_context() as db:
        bot = await channel_bot_repo.get_for_org(db, bot_id, organization_id=notice.organization_id)
        if bot is None or not bot.is_active:
            return
        run = await agent_run_repo.get_run(
            db, notice.run_id, organization_id=notice.organization_id
        )
        if run is None:
            return
        incoming = await incoming_for_run(
            db, run, bot_id=bot_id, platform_chat_id=notice.destination.platform_chat_id
        )
        if incoming is None:
            return
        admission = await ChannelMessageRouter().admission(db, run, incoming)
        if admission.verdict == "refused":
            return
        adapter = get_adapter(bot.platform)
        token = unseal_bot_token(bot)
        message = OutgoingMessage(
            platform_chat_id=notice.destination.platform_chat_id,
            text=notice.text,
            api_base_url=bot.api_base_url,
        )
    await adapter.send_message(token, message)


def ensure_channel_adapters() -> None:
    """Register the chat adapters this process lacks, starting nothing.

    The API registers them at startup; the job worker never does, and a notice
    posted from a sweep still has to reach the chat. Idempotent. No polling loop
    and no stream: a send needs neither.
    """
    from app.services.channels.discord import DiscordAdapter
    from app.services.channels.email import EmailAdapter
    from app.services.channels.imessage import ImessageAdapter
    from app.services.channels.mattermost import MattermostAdapter
    from app.services.channels.slack import SlackAdapter
    from app.services.channels.sms import SmsAdapter
    from app.services.channels.teams import teams_adapter
    from app.services.channels.telegram import TelegramAdapter

    for adapter_class in (
        SlackAdapter,
        TelegramAdapter,
        MattermostAdapter,
        DiscordAdapter,
        SmsAdapter,
        EmailAdapter,
        ImessageAdapter,
    ):
        try:
            get_adapter(adapter_class.platform)
        except KeyError:
            register_adapter(adapter_class())
    teams_adapter()
