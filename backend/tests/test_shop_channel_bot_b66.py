"""B66 — shop channel-bots CRUD + webhook_register_url parity."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.db.models.channel_bot import AUTH_METHOD_OAUTH, BOT_KIND_SHOP_CSKH
from app.schemas.shop_channel_bot import ShopChannelBotCreate
from app.services.shop_channel_bot_service import (
    ShopChannelBotService,
    shop_channel_bot_to_read,
    shop_webhook_register_url,
)

pytestmark = pytest.mark.anyio


def test_shop_webhook_register_url_zalo() -> None:
    bot_id = uuid4()
    url = shop_webhook_register_url("zalo", bot_id)
    assert url == f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/zalo/{bot_id}/webhook"


def test_shop_channel_bot_read_oauth_flag() -> None:
    bot_id = uuid4()
    tenant_id = uuid4()
    now = datetime.now(UTC)
    bot = MagicMock()
    bot.id = bot_id
    bot.platform = "zalo"
    bot.name = "OA"
    bot.is_active = True
    bot.webhook_mode = True
    bot.webhook_url = None
    bot.access_policy = {"mode": "open"}
    bot.minerp_tenant_id = tenant_id
    bot.bot_kind = BOT_KIND_SHOP_CSKH
    bot.default_kb_id = None
    bot.auth_method = AUTH_METHOD_OAUTH
    bot.zalo_oa_id = "123"
    bot.token_expires_at = None
    bot.created_at = now
    bot.updated_at = now

    read = shop_channel_bot_to_read(bot)
    assert read.oauth_connected is True
    assert read.tenant_id == tenant_id
    assert read.webhook_register_url is not None
    assert "/zalo/" in read.webhook_register_url


async def test_create_forces_webhook_mode_for_zalo() -> None:
    db = MagicMock()
    org_id = uuid4()
    tenant_id = uuid4()
    bot_id = uuid4()
    now = datetime.now(UTC)

    async def fake_create(*_args, **kwargs):
        assert kwargs["webhook_mode"] is True
        assert kwargs["bot_kind"] == BOT_KIND_SHOP_CSKH
        assert kwargs["minerp_tenant_id"] == tenant_id
        row = MagicMock()
        row.id = bot_id
        row.platform = kwargs["platform"]
        row.name = kwargs["name"]
        row.is_active = True
        row.webhook_mode = kwargs["webhook_mode"]
        row.webhook_url = kwargs["webhook_url"]
        row.access_policy = kwargs["access_policy"]
        row.minerp_tenant_id = tenant_id
        row.bot_kind = BOT_KIND_SHOP_CSKH
        row.default_kb_id = None
        row.auth_method = "token_paste"
        row.zalo_oa_id = None
        row.token_expires_at = None
        row.created_at = now
        row.updated_at = now
        return row

    data = ShopChannelBotCreate(
        platform="zalo",
        name="Test OA",
        token="x" * 20,
        tenant_id=tenant_id,
    )

    with (
        patch(
            "app.services.shop_channel_bot_service.seal_bot_token",
            return_value=MagicMock(ciphertext="sealed", key_version=1),
        ),
        patch(
            "app.services.shop_channel_bot_service.channel_bot_repo.create",
            fake_create,
        ),
    ):
        out = await ShopChannelBotService(db).create(
            data,
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
        )

    assert out.id == bot_id
    assert out.webhook_mode is True


def test_create_schema_rejects_messenger_typo_platform() -> None:
    tenant_id = uuid4()
    with pytest.raises(ValueError, match="platform=zalo or messenger"):
        ShopChannelBotCreate(
            platform="telegram",
            name="Bad",
            token="x" * 20,
            tenant_id=tenant_id,
        )
