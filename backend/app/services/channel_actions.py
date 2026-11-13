"""Use only messaging connections an agent author explicitly granted."""

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from uuid import UUID

import httpx
from aiogram.exceptions import TelegramAPIError
from pydantic import AwareDatetime, ValidationError
from slack_sdk.errors import SlackApiError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_actions._contract import (
    CAPABILITY_ID,
    CROSS_CHANNEL_PLATFORMS,
    PLATFORMS,
    TOOLS,
    ReactionReceipt,
    platform_actions,
)
from app.agents.capabilities.channel_tools._directory import (
    ChannelDestination,
    HistoryPage,
    HistoryQuery,
)
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, BadRequestError, ExternalServiceError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_exposure import AgentExposure
from app.db.models.channel_bot import ChannelBot
from app.db.session import get_db_context
from app.repositories import agent_exposure_repo, channel_bot_repo, member_repo
from app.services.agent_registry import AgentRegistryService
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import OutgoingMessage, split_thread
from app.services.channels.directory import BoundChannelDirectory

logger = logging.getLogger(__name__)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


def grant_fingerprint(exposure: AgentExposure, bot: ChannelBot) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                str(exposure.id),
                str(bot.id),
                bot.platform,
                str(bot.authorization_generation),
                sorted(set(exposure.tools) & TOOLS),
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()


def with_actions(spec: AgentSpec, tools: frozenset[str]) -> AgentSpec:
    bindings = [binding for binding in spec.capabilities if binding.id != CAPABILITY_ID]
    if tools:
        bindings.append(CapabilityBindingSpec(id=CAPABILITY_ID, config={"tools": sorted(tools)}))
    return spec.model_copy(update={"capabilities": bindings})


async def granted_connections(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID
) -> dict[UUID, tuple[AgentExposure, ChannelBot]]:
    rows = await agent_exposure_repo.list_for_agent(
        db, agent_id=agent_id, organization_id=organization_id
    )
    result: dict[UUID, tuple[AgentExposure, ChannelBot]] = {}
    for exposure in rows:
        if (
            not exposure.is_active
            or not (set(exposure.tools) & TOOLS)
            or exposure.surface not in PLATFORMS
        ):
            continue
        bot = await channel_bot_repo.get_for_org(
            db, exposure.channel_bot_id, organization_id=organization_id
        )
        if bot is not None and bot.is_active and bot.platform == exposure.surface:
            result[bot.id] = (exposure, bot)
    return result


class ChannelActionService:
    def __init__(
        self, ctx: AuthContext, agent_id: UUID, *, destination: ChannelDestination | None = None
    ) -> None:
        self.ctx = ctx
        self.agent_id = agent_id
        self.destination = destination

    async def _context(self) -> AuthContext:
        if self.ctx.user_id is None or self.ctx.subject_is_publisher_fallback:
            raise AuthorizationError(
                message="Connected chat actions need an identified member, not a publisher fallback"
            )
        async with get_db_context() as db:
            member = await member_repo.get_active(
                db, organization_id=self.ctx.organization_id, user_id=self.ctx.user_id
            )
            if member is None:
                raise AuthorizationError(message="Your organization membership is no longer active")
            ctx = replace(self.ctx, role=member.role)
            await AgentRegistryService(db).get(ctx, self.agent_id, perm=Perm.AGENTS_RUN)
            return ctx

    async def grants(self) -> dict[UUID, tuple[AgentExposure, ChannelBot]]:
        ctx = await self._context()
        async with get_db_context() as db:
            return await granted_connections(
                db, agent_id=self.agent_id, organization_id=ctx.organization_id
            )

    async def tools(
        self, db: AsyncSession, *, reviewed: Mapping[UUID, str] | None = None
    ) -> frozenset[str]:
        grants = await granted_connections(
            db, agent_id=self.agent_id, organization_id=self.ctx.organization_id
        )
        tools = {
            tool
            for exposure, bot in grants.values()
            if reviewed is None or reviewed.get(exposure.id) == grant_fingerprint(exposure, bot)
            for tool in exposure.tools
            if tool in platform_actions(bot.platform)
        }
        if tools:
            tools.add("list_chat_connections")
        return frozenset(tools)

    async def connections(self) -> str:
        grants = await self.grants()
        current = None
        if self.destination is not None and self.destination.bot_id in grants:
            channel_id, thread_id = split_thread(self.destination.platform_chat_id)
            current = {
                "bot_id": str(self.destination.bot_id),
                "channel_id": channel_id,
                "thread_id": thread_id or None,
                "message_id": self.destination.message_id,
            }
        return json.dumps(
            {
                "connections": [
                    {
                        "bot_id": str(bot.id),
                        "name": bot.name,
                        "platform": bot.platform,
                        "tools": sorted(set(exposure.tools) & platform_actions(bot.platform)),
                        "reaction_limit": 1 if bot.platform in {"telegram", "imessage"} else 8,
                        "reaction_scope": "joined_channels"
                        if bot.platform in CROSS_CHANNEL_PLATFORMS
                        else "current_message",
                    }
                    for exposure, bot in grants.values()
                ],
                "current_conversation": current,
            }
        )

    async def _bot(self, bot_id: UUID, tool: str) -> ChannelBot:
        granted = (await self.grants()).get(bot_id)
        if (
            granted is None
            or tool not in granted[0].tools
            or tool not in platform_actions(granted[1].platform)
        ):
            raise AuthorizationError(
                message="This agent has not been granted this action on that messaging connection"
            )
        return granted[1]

    async def find(self, bot_id: UUID, query: str, limit: int, cursor: str | None) -> str:
        bot = await self._bot(bot_id, "find_chat_channels")
        if len(query) > 200 or (cursor is not None and len(cursor) > 4096):
            raise BadRequestError(
                message="Use a query up to 200 characters and a returned page cursor"
            )
        try:
            page = await get_adapter(bot.platform).joined_channels(
                unseal_bot_token(bot),
                api_base_url=bot.api_base_url,
                query=query,
                limit=limit,
                cursor=cursor,
            )
        except (httpx.HTTPError, SlackApiError, ValidationError) as error:
            logger.warning(
                "channel_action_lookup_failed",
                extra={"bot_id": str(bot.id), "error_type": type(error).__name__},
            )
            raise ExternalServiceError(
                message="The messaging service refused the channel listing; this is not an empty result"
            ) from error
        return json.dumps(
            {
                "channels": [
                    {
                        "id": row.channel_id,
                        "name": row.name,
                        "purpose": row.purpose,
                        "private": row.is_private,
                    }
                    for row in page.channels
                ],
                "next_cursor": page.cursor,
            }
        )

    async def _directory(
        self, bot: ChannelBot, channel_id: str, thread_id: str | None
    ) -> BoundChannelDirectory:
        if not _IDENTIFIER.fullmatch(channel_id) or (
            thread_id is not None and not _IDENTIFIER.fullmatch(thread_id)
        ):
            raise BadRequestError(
                message="Use channel and thread IDs returned by this messaging connection"
            )
        token = unseal_bot_token(bot)
        adapter = get_adapter(bot.platform)
        await adapter.require_joined_channel(token, channel_id, api_base_url=bot.api_base_url)
        if thread_id is not None:
            await adapter.require_channel_thread(
                token, channel_id, thread_id, api_base_url=bot.api_base_url
            )
        return BoundChannelDirectory(
            adapter=adapter,
            bot_token=token,
            bot_id=bot.id,
            channel_id=channel_id,
            thread_id=thread_id,
            api_base_url=bot.api_base_url,
        )

    async def read(
        self,
        bot_id: UUID,
        channel_id: str,
        *,
        thread_id: str | None,
        query: str,
        after: AwareDatetime | None,
        before: AwareDatetime | None,
        author_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> HistoryPage:
        bot = await self._bot(bot_id, "read_chat_messages")
        filters = HistoryQuery(
            query=query, after=after, before=before, author_id=author_id, cursor=cursor
        )
        try:
            directory = await self._directory(bot, channel_id, thread_id)
            return await directory.history_page(
                limit=limit, scope="thread" if thread_id else "channel", filters=filters
            )
        except (httpx.HTTPError, SlackApiError, ValidationError) as error:
            logger.warning(
                "channel_action_read_failed",
                extra={"bot_id": str(bot.id), "error_type": type(error).__name__},
            )
            raise ExternalServiceError(
                message="The messaging service refused this channel or thread; no messages were read"
            ) from error

    async def send(self, bot_id: UUID, channel_id: str, *, text: str, thread_id: str | None) -> str:
        bot = await self._bot(bot_id, "send_chat_message")
        if not text.strip() or len(text) > 12000:
            raise BadRequestError(
                message="Send a nonempty message up to 12,000 characters; publish a longer report as an App"
            )
        try:
            directory = await self._directory(bot, channel_id, thread_id)
            await directory.adapter.send_message(
                directory.bot_token,
                OutgoingMessage(
                    platform_chat_id=channel_id + (":" + thread_id if thread_id else ""),
                    text=text,
                    api_base_url=bot.api_base_url,
                ),
            )
        except (httpx.HTTPError, SlackApiError, ValidationError) as error:
            logger.warning(
                "channel_action_send_uncertain",
                extra={"bot_id": str(bot.id), "error_type": type(error).__name__},
            )
            raise ExternalServiceError(
                message="Delivery was not confirmed. Check the destination before retrying; the platform may already have accepted the message"
            ) from error
        return f"The platform accepted the message for channel {channel_id}" + (
            f", thread {thread_id}." if thread_id else " as a new post."
        )

    async def react(
        self,
        bot_id: UUID,
        channel_id: str,
        message_id: str,
        emojis: list[str],
        *,
        reaction_only: bool,
    ) -> str:
        bot = await self._bot(bot_id, "react_to_chat_message")
        if (
            not _IDENTIFIER.fullmatch(message_id)
            or not 1 <= len(emojis) <= 8
            or any(re.fullmatch(r"[a-z0-9_+-]{1,64}", emoji) is None for emoji in emojis)
        ):
            raise BadRequestError(
                message="Use a real message id and 1-8 emoji names without colons"
            )
        choices = list(dict.fromkeys(emojis))
        if bot.platform in {"telegram", "imessage"} and len(choices) > 1:
            raise BadRequestError(
                message="This platform allows one bot reaction per message; choose one emoji"
            )
        if bot.platform in CROSS_CHANNEL_PLATFORMS:
            directory = await self._directory(bot, channel_id, None)
            adapter, token = directory.adapter, directory.bot_token
        else:
            # Telegram cannot fetch arbitrary messages; iMessage tapbacks also need
            # a verified message GUID. Admission supplied this exact destination.
            if (
                self.destination is None
                or self.destination.bot_id != bot.id
                or split_thread(self.destination.platform_chat_id)[0] != channel_id
                or self.destination.message_id != message_id
            ):
                raise AuthorizationError(
                    message="Reactions on this platform are limited to the current verified message"
                )
            adapter, token = get_adapter(bot.platform), unseal_bot_token(bot)
        applied: list[str] = []
        failed: list[str] = []
        not_attempted: list[str] = []
        for index, emoji in enumerate(choices):
            try:
                await adapter.react_to_message(
                    token,
                    channel_id,
                    message_id,
                    emoji,
                    api_base_url=bot.api_base_url,
                )
                applied.append(emoji)
            except httpx.HTTPError, SlackApiError, TelegramAPIError, ValidationError:
                logger.warning(
                    "channel_reaction_unconfirmed",
                    extra={"bot_id": str(bot.id), "message_id": message_id},
                )
                failed.append(emoji)
                not_attempted = choices[index + 1 :]
                break
        return ReactionReceipt(
            bot_id=bot.id,
            channel_id=channel_id,
            message_id=message_id,
            applied=applied,
            failed=failed,
            not_attempted=not_attempted,
            reaction_only=reaction_only and not failed,
        ).model_dump_json()
