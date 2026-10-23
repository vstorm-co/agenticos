"""Greeting somebody who just joined, in the chat apps their organization connected (#2301).

A new member's first contact with the organization's agents should not wait for
them to find the console. Where the organization turned it on, each active Slack,
Mattermost and Teams bot looks them up by address and, where it finds them, sends
one direct message: the organization's own words, or who it is, that they can
ask here, and where the console is.

Best-effort by contract, and so one attempt: a platform that cannot find them,
or is down, is logged and the next one still tries. Retrying the whole greeting
would greet them twice on every platform that had already succeeded.
"""

import contextlib
import logging
from collections.abc import AsyncGenerator, Callable
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.channel_bot import ChannelBot
from app.repositories import (
    channel_bot_repo,
    member_repo,
    organization_repo,
    teams_conversation_repo,
    user_repo,
)
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import ChannelAdapter
from app.services.channels.exceptions import ChannelNotConfigured

logger = logging.getLogger(__name__)

GREETING = {
    "en": (
        "Welcome to {organization}! I'm {bot}, the AI assistant here. Ask me anything right "
        "in this chat - or open the console: {url}"
    ),
    "pl": (
        "Witaj w {organization}! Jestem {bot}, asystent AI w tej organizacji. Zapytaj mnie o "
        "cokolwiek tutaj na czacie - albo otwórz konsolę: {url}"
    ),
    "de": (
        "Willkommen bei {organization}! Ich bin {bot}, der KI-Assistent hier. Fragen Sie mich "
        "alles direkt in diesem Chat - die Konsole finden Sie hier: {url}"
    ),
}

PLATFORMS = ("slack", "mattermost", "teams")


@contextlib.asynccontextmanager
async def _adapter(platform: str) -> AsyncGenerator[ChannelAdapter]:
    """The process's adapter, or one made for this greeting and closed after it.

    The API registers every adapter at start-up; a job worker registers none.
    """
    registered: ChannelAdapter | None
    try:
        registered = get_adapter(platform)
    except KeyError:
        registered = None
    if registered is not None:
        yield registered
        return
    adapter: ChannelAdapter
    if platform == "teams":
        from app.services.channels.teams import teams_adapter

        yield teams_adapter()
        return
    if platform == "slack":
        from app.services.channels.slack import SlackAdapter

        adapter = SlackAdapter()
    else:
        from app.services.channels.mattermost import MattermostAdapter

        adapter = MattermostAdapter()
    try:
        yield adapter
    finally:
        await adapter.aclose()


async def welcome(db: AsyncSession, organization_id: UUID, user_id: UUID) -> int:
    """Greet one new member on every connected platform that knows them. Returns how many did."""
    user = await user_repo.get_by_id(db, user_id)
    organization = await organization_repo.get_by_id(db, organization_id)
    if (
        user is None
        or organization is None
        or not user.is_active
        or not organization.welcome_dm_enabled
    ):
        return 0
    # Read again here, not trusted from when the greeting was queued: somebody
    # removed in between is not welcomed to an organization they have left.
    if await member_repo.get_active(db, organization_id=organization_id, user_id=user_id) is None:
        return 0
    template = organization.welcome_dm_text or GREETING.get(user.locale or "", GREETING["en"])
    return await direct_message(
        db,
        organization_id,
        user.email,
        lambda bot: _fill(
            template, organization=organization.name, bot=bot.name, url=settings.FRONTEND_URL
        ),
    )


async def direct_message(
    db: AsyncSession, organization_id: UUID, email: str, text_for: Callable[[ChannelBot], str]
) -> int:
    """Write to one person from every active chat-app bot that knows them. Returns how many did.

    `text_for` words it for each bot, which may name itself. Best-effort: a
    platform that cannot find them or is down is logged, and the next still tries.
    """
    bots = [
        bot
        for platform in PLATFORMS
        for bot in await channel_bot_repo.get_by_platform(
            db, platform, organization_id=organization_id
        )
        if bot.is_active
    ]
    if not bots:
        return 0
    shared = await teams_conversation_repo.list_shared(db, organization_id=organization_id)
    sent = 0
    for bot in bots:
        places = [row.key for row in shared if row.bot_id == bot.id]
        if await _greet(bot, email, text_for(bot), places):
            sent += 1
    return sent


def _fill(template: str, **values: str) -> str:
    """The template with its `{name}` placeholders filled, and nothing else read from it.

    Not `str.format`: an organization writes its own greeting, and format would
    fail on a stray brace in it - or read attributes off the values for a
    placeholder like `{bot.__class__}`.
    """
    for name, value in values.items():
        template = template.replace(f"{{{name}}}", value)
    return template


async def _greet(bot: ChannelBot, email: str, text: str, places: list[str]) -> bool:
    try:
        async with _adapter(bot.platform) as adapter:
            return await adapter.welcome(
                unseal_bot_token(bot),
                email,
                text,
                api_base_url=bot.api_base_url,
                places=places,
            )
    except httpx.HTTPError, ChannelNotConfigured, ValueError, KeyError:
        # The vendor's own text stays in the log; the next platform still tries.
        logger.exception("welcome_failed", extra={"bot_id": str(bot.id), "platform": bot.platform})
        return False
