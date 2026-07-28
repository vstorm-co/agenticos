"""ChannelBotService — business logic for bot management (PostgreSQL async).

A bot token is sealed with :mod:`app.core.vault`, bound to the organization the
bot belongs to. It used to be Fernet-encrypted with one deployment-wide key,
which meant a ciphertext copied from one tenant's row into another's decrypted
happily — the token itself is what talks to Slack or Telegram as that
organization, so that was a tenant boundary with nothing behind it.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.vault import SealedSecret, VaultScope, seal, unseal
from app.db.models.channel_bot import ChannelBot
from app.repositories import channel_bot_repo, channel_session_repo
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
from app.services.channels import get_adapter

logger = logging.getLogger(__name__)


def seal_bot_token(token: str, *, organization_id: UUID) -> SealedSecret:
    """Seal a bot token for the organization that owns the bot."""
    return seal(token, scope=VaultScope.organization(organization_id))


def unseal_bot_token(bot: ChannelBot) -> str:
    """Recover a bot's token.

    A module-level function rather than a method because the inbound paths —
    the webhook router and the polling loop at startup — have the row and no
    service, and the row is what carries the organization the envelope is bound
    to.
    """
    return unseal(
        bot.token_encrypted,
        scope=VaultScope.organization(bot.organization_id),
        key_version=bot.secret_key_version,
    )


class ChannelBotService:
    """Service for channel bot management.

    ``organization_id`` is the tenant every management call is scoped to. It is
    ``None`` only on the inbound path (webhook / poller), where no member is
    making the request and the bot row itself carries the organization — those
    callers may use :meth:`find_active` and :meth:`get_decrypted_token` and
    nothing else.
    """

    def __init__(self, db: AsyncSession, organization_id: UUID | None = None) -> None:
        self.db = db
        self.organization_id = organization_id

    @property
    def _org_id(self) -> UUID:
        """The tenant for management calls, or a loud failure if unscoped."""
        if self.organization_id is None:
            raise RuntimeError(
                "ChannelBotService was built without an organization — this instance may only "
                "serve inbound dispatch. Use the org-scoped dependency for management calls."
            )
        return self.organization_id

    async def create(self, data: ChannelBotCreate) -> ChannelBot:
        """Create a new channel bot with a sealed token."""
        sealed = seal_bot_token(data.token, organization_id=self._org_id)
        webhook_secret = secrets.token_urlsafe(32) if data.webhook_mode else None
        return await channel_bot_repo.create(
            self.db,
            organization_id=self._org_id,
            platform=data.platform,
            name=data.name,
            token_encrypted=sealed.ciphertext,
            secret_key_version=sealed.key_version,
            webhook_mode=data.webhook_mode,
            webhook_url=data.webhook_url,
            webhook_secret=webhook_secret,
            access_policy=data.access_policy.model_dump(),
            ai_model_override=data.ai_model_override,
            system_prompt_override=data.system_prompt_override,
        )

    async def get(self, bot_id: UUID) -> ChannelBot:
        """Get one of this organization's bots; raises NotFoundError if not found.

        A bot belonging to another organization is reported as missing rather
        than forbidden, so the endpoint cannot be used to probe for bot ids.
        """
        bot = await channel_bot_repo.get_for_org(self.db, bot_id, organization_id=self._org_id)
        if not bot:
            raise NotFoundError(
                message="Channel bot not found",
                details={"bot_id": str(bot_id)},
            )
        return bot

    async def find_active(self, bot_id: UUID) -> ChannelBot | None:
        """Return an active bot by ID, or None (inbound webhook / poller path)."""
        bot = await channel_bot_repo.get_for_inbound(self.db, bot_id)
        if not bot or not bot.is_active:
            return None
        return bot

    async def list_all(self, *, skip: int = 0, limit: int = 50) -> tuple[list[ChannelBot], int]:
        """List this organization's bots with total count."""
        bots = await channel_bot_repo.list_for_org(
            self.db, organization_id=self._org_id, skip=skip, limit=limit
        )
        total = await channel_bot_repo.count(self.db, organization_id=self._org_id)
        return bots, total

    async def list_by_platform(self, platform: str | None = None) -> list[ChannelBot]:
        """Return this organization's bots, optionally filtered by platform."""
        if platform:
            return await channel_bot_repo.get_by_platform(
                self.db, platform, organization_id=self._org_id
            )
        return await channel_bot_repo.list_for_org(self.db, organization_id=self._org_id)

    async def update(self, bot_id: UUID, data: ChannelBotUpdate) -> ChannelBot:
        """Update a channel bot."""
        bot = await self.get(bot_id)
        update_data = data.model_dump(exclude_unset=True)
        if "token" in update_data:
            sealed = seal_bot_token(update_data.pop("token"), organization_id=self._org_id)
            update_data["token_encrypted"] = sealed.ciphertext
            update_data["secret_key_version"] = sealed.key_version
        if "access_policy" in update_data and update_data["access_policy"] is not None:
            policy = update_data["access_policy"]
            update_data["access_policy"] = (
                policy.model_dump() if hasattr(policy, "model_dump") else policy
            )
        return await channel_bot_repo.update(self.db, db_bot=bot, update_data=update_data)

    async def delete(self, bot_id: UUID) -> None:
        """Delete a channel bot."""
        await self.get(bot_id)
        await channel_bot_repo.delete(self.db, bot_id, organization_id=self._org_id)

    async def activate(self, bot_id: UUID) -> ChannelBot:
        """Set is_active = True."""
        bot = await self.get(bot_id)
        return await channel_bot_repo.update(self.db, db_bot=bot, update_data={"is_active": True})

    async def deactivate(self, bot_id: UUID) -> ChannelBot:
        """Set is_active = False."""
        bot = await self.get(bot_id)
        return await channel_bot_repo.update(self.db, db_bot=bot, update_data={"is_active": False})

    def get_decrypted_token(self, bot: ChannelBot) -> str:
        """Return the bot's token in the clear, for an immediate platform call."""
        return unseal_bot_token(bot)

    async def get_active_polling_bots(self, platform: str) -> list[ChannelBot]:
        """Return active polling (non-webhook) bots for the given platform.

        Deployment-wide, not org-scoped — the poller serves every tenant. Each
        bot returned carries its own ``organization_id``.
        """
        return await channel_bot_repo.get_active_polling_bots(self.db, platform)

    async def list_sessions(
        self, bot_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> tuple[list, int]:
        """List channel sessions for this bot."""
        items = await channel_session_repo.list_by_bot(self.db, bot_id, skip=skip, limit=limit)
        total = await channel_session_repo.count_by_bot(self.db, bot_id)
        return items, total

    async def register_webhook(self, bot_id: UUID) -> dict[str, Any]:
        """Register a webhook URL with the bot's platform.

        Looks up the bot, picks the adapter for its platform, builds the platform-specific
        webhook URL from settings, and asks the adapter to register it.
        """
        bot = await self.get(bot_id)
        adapter = get_adapter(bot.platform)
        token = self.get_decrypted_token(bot)
        webhook_url = (
            f"{settings.TELEGRAM_WEBHOOK_BASE_URL}/api/v1/channels/{bot.platform}/{bot_id}/webhook"
        )
        success = await adapter.register_webhook(token, url=webhook_url, secret=bot.webhook_secret)
        return {"success": success, "webhook_url": webhook_url}

    async def delete_webhook(self, bot_id: UUID) -> dict[str, Any]:
        """Remove the webhook from the bot's platform (switches to polling mode)."""
        bot = await self.get(bot_id)
        adapter = get_adapter(bot.platform)
        token = self.get_decrypted_token(bot)
        success = await adapter.delete_webhook(token)
        return {"success": success}
