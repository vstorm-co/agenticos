"""Whether a channel thread's participant is still in the channel.

`/chat` shows a channel thread to everybody whose linked chat account has
written in it. That record - `messages.channel_identity_id` - says who *spoke*,
and speaking once used to keep the thread readable after the platform removed
them from the channel: a second access path to channel content that outlived
the access the platform grants (#641). This module is the check that closes it:
every participation claim is confirmed against the platform's current
membership before the listing shows the thread or the read opens it.

The confirmation is one `adapter.is_channel_member` call per (bot, chat,
account), behind a short shared-Redis cache so a listing does not become an API
call per channel per page. It **fails closed, loudly**: a platform that cannot
answer (`ChannelDirectoryUnsupported`), a bot or adapter that is gone, and a
call that errors all read as "not a member", each with a log line. Refusing a
participant for a cache's TTL is the acceptable cost; showing a removed one the
room's transcript is the defect this exists to prevent. The owner of a thread
and anybody it was explicitly shared with are not this module's business - both
ways in survive a refusal here.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.db.models.channel_bot import ChannelBot
from app.repositories import channel_bot as channel_bot_repo
from app.repositories import conversation as conversation_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import ChannelDirectoryUnsupported

logger = logging.getLogger(__name__)

MEMBERSHIP_TTL_SECONDS = 60
"""How long one membership answer is trusted.

Short on purpose: it is the window in which somebody removed from a channel
can still open its thread, so it is a minute rather than the fifteen the
dedupe claim gets. Refusals are cached for the same window - a platform that
is down would otherwise be asked again, with a timeout, on every listing.
"""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the lifespan next to where the client is created, the same
    contract as `dedupe.configure`. Unconfigured is not unsafe here, only
    slow: every check goes to the platform.
    """
    global _redis
    _redis = redis


def _key(bot_id: UUID, platform_chat_id: str, platform_user_id: str) -> str:
    return f"channel:member:{bot_id}:{platform_chat_id}:{platform_user_id}"


async def _cached(key: str) -> bool | None:
    """The remembered answer, or None for both "no entry" and "no Redis"."""
    if _redis is None:
        return None
    try:
        value = await _redis.get(key)
    except Exception:
        logger.warning("channel_membership_cache_unavailable", exc_info=True)
        return None
    if value is None:
        return None
    return value == "1"


async def _remember(key: str, member: bool) -> None:
    if _redis is None:
        return
    try:
        await _redis.set(key, "1" if member else "0", ttl=MEMBERSHIP_TTL_SECONDS)
    except Exception:
        logger.warning("channel_membership_cache_unavailable", exc_info=True)


async def is_still_member(bot: ChannelBot, platform_chat_id: str, platform_user_id: str) -> bool:
    """Whether this account is in this channel right now, as far as we can know.

    False means "could not be confirmed", not always "was removed": a platform
    that will not tell a bot, an adapter that is not registered, a token that
    fails to unseal and a call that errors all refuse, because an access check
    that fails open is not one. Each cause is logged; the answer - either
    answer - is cached for :data:`MEMBERSHIP_TTL_SECONDS`.
    """
    key = _key(bot.id, platform_chat_id, platform_user_id)
    cached = await _cached(key)
    if cached is not None:
        return cached
    try:
        adapter = get_adapter(bot.platform)
        member = await adapter.is_channel_member(
            unseal_bot_token(bot),
            platform_chat_id,
            platform_user_id,
            api_base_url=bot.api_base_url,
        )
    except ChannelDirectoryUnsupported as exc:
        logger.info(
            "Channel membership not confirmable, refusing: bot=%s chat=%s - %s",
            bot.id,
            platform_chat_id,
            exc,
        )
        member = False
    except Exception:
        logger.warning(
            "Channel membership check failed, refusing: bot=%s chat=%s",
            bot.id,
            platform_chat_id,
            exc_info=True,
        )
        member = False
    await _remember(key, member)
    return member


async def _confirmed(
    db: AsyncSession, claims: list[conversation_repo.ParticipationClaim]
) -> set[UUID]:
    """The conversations whose claims held up against the platform.

    One membership question per distinct (bot, chat, account) however many
    threads hang off it, asked concurrently - on a cold cache each is a network
    round trip, and a listing is waiting.
    """
    if not claims:
        return set()
    bots = await channel_bot_repo.get_by_ids(db, {claim.bot_id for claim in claims})
    questions = {
        (claim.bot_id, claim.platform_chat_id, claim.platform_user_id)
        for claim in claims
        if claim.bot_id in bots
    }
    ordered = sorted(questions, key=str)
    answers = await asyncio.gather(
        *(is_still_member(bots[bot_id], chat, account) for bot_id, chat, account in ordered)
    )
    confirmed = {question for question, answer in zip(ordered, answers, strict=True) if answer}
    return {
        claim.conversation_id
        for claim in claims
        if (claim.bot_id, claim.platform_chat_id, claim.platform_user_id) in confirmed
    }


async def confirmed_participant_threads(
    db: AsyncSession, *, user_id: UUID, organization_id: UUID
) -> set[UUID]:
    """The channel threads this user may currently be shown, listing-side.

    Everything a chat account of theirs spoke in, kept only where the platform
    confirms the account is still in the channel. This is what
    `ConversationService.list_conversations` hands the repository as the vetted
    participation set.
    """
    claims = await conversation_repo.participation_claims(
        db, user_id=user_id, organization_id=organization_id
    )
    return await _confirmed(db, claims)


async def confirms_participation(db: AsyncSession, *, conversation_id: UUID, user_id: UUID) -> bool:
    """The read-side of the same rule: may participation open *this* thread.

    The same claims, narrowed to one conversation, so the list and the read
    cannot disagree - a thread the listing refuses is a thread the read
    refuses, and the other way around.
    """
    claims = await conversation_repo.participation_claims(
        db, user_id=user_id, conversation_id=conversation_id
    )
    return conversation_id in await _confirmed(db, claims)
