"""Opt-in private chat notifications using the existing channel transports.

Route replacement revokes the old grant, including queued deliveries. An
unacknowledged provider request is never blindly resent. Confirmed non-acceptance
may defer through the shared queue; the next claim clears that retry authority.
"""

from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.notification import Notification
from app.db.models.notification_delivery import NotificationDelivery
from app.repositories import member_repo
from app.repositories import notification_route as route_repo
from app.schemas.channel_bot import AccessPolicy
from app.schemas.notification_route import (
    NotificationDestinationRead,
    NotificationRouteList,
    NotificationRouteRead,
    NotificationRouteUpdate,
)
from app.services.channel_bot import unseal_bot_token
from app.services.channels.base import ChannelAdapter, OutgoingMessage, channel_key
from app.services.notification_center import absolute_context_url


def available(destination: route_repo.Destination) -> bool:
    """A private session remains usable under the operator's current bot policy."""
    session, bot, identity = destination
    try:
        policy = (
            AccessPolicy.model_validate_json(bot.access_policy)
            if isinstance(bot.access_policy, str)
            else AccessPolicy.model_validate(bot.access_policy or {})
        )
    except ValidationError:
        return False
    if policy.mode == "group_only":
        return False
    if policy.mode == "whitelist" and identity.platform_user_id not in policy.whitelist:
        return False
    linked = identity.updated_at or identity.created_at
    if (
        bot.platform == "sms"
        and settings.SMS_LINK_MAX_AGE_DAYS > 0
        and datetime.now(UTC) - linked > timedelta(days=settings.SMS_LINK_MAX_AGE_DAYS)
    ):
        return False
    return session.chat_type == "private"


class NotificationRouteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _human(self, ctx: AuthContext) -> UUID:
        if (
            ctx.user_id is None
            or ctx.api_key_id is not None
            or ctx.routine_id is not None
            or ctx.fired_as_creator is not None
            or ctx.subject_is_publisher_fallback
            or current_impersonator() is not None
            or await member_repo.get_active(
                self.db, organization_id=ctx.organization_id, user_id=ctx.user_id
            )
            is None
        ):
            raise AuthorizationError(
                message="Notification destinations require your own console session"
            )
        return ctx.user_id

    async def list(self, ctx: AuthContext) -> NotificationRouteList:
        user_id = await self._human(ctx)
        destinations = [
            item
            for item in await route_repo.destinations(
                self.db, organization_id=ctx.organization_id, user_id=user_id
            )
            if available(item)
        ]
        routes = await route_repo.routes(
            self.db, organization_id=ctx.organization_id, user_ids=[user_id]
        )
        eligible = {session.id for session, _, _ in destinations}
        for route in routes:
            if route.session_id not in eligible:
                selected = await route_repo.destinations(
                    self.db,
                    organization_id=ctx.organization_id,
                    user_id=user_id,
                    session_id=route.session_id,
                )
                if selected and available(selected[0]):
                    destinations.append(selected[0])
                    eligible.add(route.session_id)
        items: list[NotificationRouteRead] = []
        for route in routes:
            current = await route_repo.current(
                self.db,
                route_id=route.id,
                organization_id=ctx.organization_id,
                user_id=user_id,
                channel=route.channel,
            )
            items.append(
                NotificationRouteRead.model_validate(
                    {
                        "id": route.id,
                        "channel": route.channel,
                        "session_id": route.session_id,
                        "available": current is not None and route.session_id in eligible,
                    }
                )
            )
        return NotificationRouteList(
            items=items,
            destinations=[
                NotificationDestinationRead.model_validate(
                    {
                        "session_id": session.id,
                        "channel": bot.platform,
                        "bot_name": bot.name,
                        "account_name": identity.platform_display_name
                        or identity.platform_username
                        or identity.platform_user_id,
                    }
                )
                for session, bot, identity in destinations
            ],
        )

    async def replace(
        self, ctx: AuthContext, data: NotificationRouteUpdate
    ) -> NotificationRouteList:
        user_id = await self._human(ctx)
        destination: route_repo.Destination | None = None
        if data.session_id is not None:
            found = await route_repo.destinations(
                self.db,
                organization_id=ctx.organization_id,
                user_id=user_id,
                session_id=data.session_id,
            )
            if not found or found[0][1].platform != data.channel or not available(found[0]):
                raise NotFoundError(message="Private notification destination not available")
            destination = found[0]
        await route_repo.replace(
            self.db,
            organization_id=ctx.organization_id,
            user_id=user_id,
            channel=data.channel,
            destination=destination,
        )
        await record_audit(
            self.db,
            actor_user_id=user_id,
            organization_id=ctx.organization_id,
            action="notification.destination_changed",
            target_type="user",
            target_id=str(user_id),
            details={"channel": data.channel, "enabled": destination is not None},
        )
        return await self.list(ctx)

    async def deliver(
        self,
        delivery: NotificationDelivery,
        notification: Notification,
        *,
        summary: str,
        context_url: str | None,
    ) -> Literal["sent", "skipped"]:
        if notification.organization_id is None or delivery.route_id is None:
            return "skipped"
        route = await route_repo.current(
            self.db,
            route_id=delivery.route_id,
            organization_id=notification.organization_id,
            user_id=notification.recipient_user_id,
            channel=delivery.channel,
        )
        if route is None:
            return "skipped"
        found = await route_repo.destinations(
            self.db,
            organization_id=notification.organization_id,
            user_id=notification.recipient_user_id,
            session_id=route.session_id,
        )
        if not found or not available(found[0]):
            return "skipped"
        await self._send(found[0], summary=summary, context_url=context_url)
        return "sent"

    async def _send(
        self, destination: route_repo.Destination, *, summary: str, context_url: str | None
    ) -> None:
        session, bot, _ = destination
        # Each worker owns and closes its transports; no API-process registry is needed.
        async with AsyncExitStack() as stack:
            adapter: ChannelAdapter
            if bot.platform == "telegram":
                from app.services.channels.telegram import TelegramAdapter

                adapter = TelegramAdapter()
            elif bot.platform == "slack":
                from app.services.channels.slack import SlackAdapter

                slack = SlackAdapter()
                stack.push_async_callback(slack.aclose)
                adapter = slack
            elif bot.platform == "mattermost":
                from app.services.channels.mattermost import MattermostAdapter

                mattermost = MattermostAdapter()
                stack.push_async_callback(mattermost.aclose)
                adapter = mattermost
            elif bot.platform == "teams":
                from app.services.channels.teams import ConversationRef, TeamsAdapter

                ref = await route_repo.teams_reference(
                    self.db, bot=bot, key=channel_key(session.platform_chat_id)
                )
                if ref is None:
                    raise NotFoundError(message="Private Teams destination no longer available")
                known = ConversationRef(
                    conversation_id=ref.conversation_id,
                    service_url=ref.service_url,
                    conversation_type=ref.conversation_type,
                    tenant_id=ref.tenant_id,
                    name=ref.name,
                )
                if known.key != channel_key(session.platform_chat_id):
                    raise NotFoundError(message="Private Teams destination no longer available")
                teams = TeamsAdapter()
                stack.push_async_callback(teams.aclose)
                teams.know(known)
                adapter = teams
            elif bot.platform == "sms":
                from app.services.channels.sms import SmsAdapter

                sms = SmsAdapter()
                stack.push_async_callback(sms.aclose)
                adapter = sms
            elif bot.platform == "discord":
                from app.services.channels.discord import DiscordAdapter

                discord = DiscordAdapter()
                stack.push_async_callback(discord.aclose)
                adapter = discord
            elif bot.platform == "imessage":
                from app.services.channels.imessage import ImessageAdapter

                imessage = ImessageAdapter()
                stack.push_async_callback(imessage.aclose)
                adapter = imessage
            else:
                raise ValueError("Unsupported notification transport")
            url = absolute_context_url(context_url)
            await adapter.send_notification(
                unseal_bot_token(bot),
                OutgoingMessage(
                    platform_chat_id=session.platform_chat_id,
                    text=summary,
                    api_base_url=bot.api_base_url,
                ),
                context_url=url,
            )
