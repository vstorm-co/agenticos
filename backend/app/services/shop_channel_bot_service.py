"""Shop CSKH channel bots — org + minerp tenant scoped CRUD (D3 B66)."""

from __future__ import annotations

import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.vault import VaultScope, seal
from app.db.models.channel_bot import (
    AUTH_METHOD_OAUTH,
    AUTH_METHOD_TOKEN_PASTE,
    BOT_KIND_SHOP_CSKH,
    ChannelBot,
)
from app.repositories import channel_bot_repo
from app.repositories import shop_channel_bot as shop_bot_repo
from app.schemas.channel_bot import AccessPolicy
from app.schemas.shop_channel_bot import (
    ShopChannelBotCreate,
    ShopChannelBotList,
    ShopChannelBotRead,
    ShopChannelBotUpdate,
)
from app.services.channel_bot import seal_bot_token
from app.services.channels import inbound_webhook_url


def shop_webhook_register_url(platform: str, bot_id: UUID) -> str | None:
    """Studio-facing webhook URL (multi-agent path layout).

    Zalo/Messenger receivers are not mounted on Agentra yet; the URL matches
    multi-agent so operators can paste it when we wire inbound adapters.
    """
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    shop_paths = {
        "zalo": f"/api/v1/zalo/{bot_id}/webhook",
        "messenger": f"/api/v1/messenger/{bot_id}/webhook",
    }
    if platform in shop_paths:
        return f"{base}{shop_paths[platform]}"
    try:
        return inbound_webhook_url(platform, bot_id)
    except KeyError:
        return None


def shop_channel_bot_to_read(bot: ChannelBot) -> ShopChannelBotRead:
    policy = AccessPolicy.model_validate(bot.access_policy or {})
    webhook_register_url = None
    if bot.webhook_mode:
        webhook_register_url = shop_webhook_register_url(bot.platform, bot.id)
    return ShopChannelBotRead(
        id=bot.id,
        platform=bot.platform,
        name=bot.name,
        is_active=bot.is_active,
        webhook_mode=bot.webhook_mode,
        webhook_url=bot.webhook_url,
        access_policy=policy,
        tenant_id=bot.minerp_tenant_id,
        bot_kind=bot.bot_kind,  # type: ignore[arg-type]
        default_kb_id=bot.default_kb_id,
        webhook_register_url=webhook_register_url,
        auth_method=bot.auth_method,  # type: ignore[arg-type]
        zalo_oa_id=bot.zalo_oa_id,
        oauth_connected=bot.auth_method == AUTH_METHOD_OAUTH,
        token_expires_at=bot.token_expires_at,
        created_at=bot.created_at,
        updated_at=bot.updated_at,
    )


class ShopChannelBotService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_tenant(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> ShopChannelBotList:
        items = await shop_bot_repo.list_for_shop(
            self.db,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            skip=skip,
            limit=limit,
        )
        total = await shop_bot_repo.count_for_shop(
            self.db,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        return ShopChannelBotList(
            items=[shop_channel_bot_to_read(b) for b in items],
            total=total,
        )

    async def get_for_tenant(
        self,
        bot_id: UUID,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
    ) -> ChannelBot:
        bot = await shop_bot_repo.get_for_shop(
            self.db,
            bot_id=bot_id,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        if not bot:
            raise NotFoundError(
                message="Channel bot not found",
                details={
                    "bot_id": str(bot_id),
                    "tenant_id": str(minerp_tenant_id),
                },
            )
        return bot

    async def create(
        self,
        data: ShopChannelBotCreate,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
    ) -> ShopChannelBotRead:
        webhook_mode = data.webhook_mode
        if data.bot_kind == BOT_KIND_SHOP_CSKH and data.platform in ("zalo", "messenger"):
            webhook_mode = True
        webhook_secret = (data.webhook_secret or "").strip() or None
        if webhook_mode and not webhook_secret:
            webhook_secret = secrets.token_urlsafe(32)

        sealed = seal_bot_token(data.token, organization_id=organization_id)
        webhook_secret_encrypted = _seal_optional(
            webhook_secret,
            organization_id=organization_id,
            key_version=sealed.key_version,
        )

        bot = await channel_bot_repo.create(
            self.db,
            organization_id=organization_id,
            platform=data.platform,
            name=data.name,
            token_encrypted=sealed.ciphertext,
            secret_key_version=sealed.key_version,
            webhook_mode=webhook_mode,
            webhook_url=data.webhook_url,
            webhook_secret_encrypted=webhook_secret_encrypted,
            access_policy=data.access_policy.model_dump(),
            minerp_tenant_id=minerp_tenant_id,
            bot_kind=BOT_KIND_SHOP_CSKH,
            default_kb_id=data.default_kb_id,
            auth_method=AUTH_METHOD_TOKEN_PASTE,
        )
        return shop_channel_bot_to_read(bot)

    async def update(
        self,
        bot_id: UUID,
        data: ShopChannelBotUpdate,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
    ) -> ShopChannelBotRead:
        bot = await self.get_for_tenant(
            bot_id,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        update_data = data.model_dump(exclude_unset=True)
        if "token" in update_data:
            token = update_data.pop("token")
            sealed = seal_bot_token(token, organization_id=organization_id)
            update_data["token_encrypted"] = sealed.ciphertext
            update_data["secret_key_version"] = sealed.key_version
        if "access_policy" in update_data and update_data["access_policy"] is not None:
            policy = update_data["access_policy"]
            update_data["access_policy"] = (
                policy.model_dump() if hasattr(policy, "model_dump") else policy
            )
        if "webhook_secret" in update_data:
            raw = update_data.pop("webhook_secret")
            if raw is not None:
                update_data["webhook_secret_encrypted"] = _seal_optional(
                    raw.strip() or None,
                    organization_id=organization_id,
                    key_version=bot.secret_key_version,
                )
        # Studio-only fields — not stored on Agentra channel_bots yet.
        for studio_only in (
            "ai_model_override",
            "system_prompt_override",
            "agent_mode",
            "enabled_specialists",
        ):
            update_data.pop(studio_only, None)

        updated = await channel_bot_repo.update(
            self.db, db_bot=bot, update_data=update_data
        )
        return shop_channel_bot_to_read(updated)

    async def delete(
        self,
        bot_id: UUID,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
    ) -> None:
        await self.get_for_tenant(
            bot_id,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        deleted = await channel_bot_repo.delete(
            self.db, bot_id, organization_id=organization_id
        )
        if not deleted:
            raise NotFoundError(
                message="Channel bot not found",
                details={"bot_id": str(bot_id)},
            )


def _seal_optional(
    value: str | None,
    *,
    organization_id: UUID,
    key_version: int,
) -> str | None:
    if value is None:
        return None
    return seal(
        value,
        scope=VaultScope.organization(organization_id),
        key_version=key_version,
    ).ciphertext
