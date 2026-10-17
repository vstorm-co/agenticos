"""B59 — Shop assistant persona settings."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.schemas.shop_assistant_persona import ShopAssistantPersonaPatch
from app.services.shop_assistant_persona_settings import ShopAssistantPersonaService

pytestmark = pytest.mark.anyio


async def test_patch_persona_updates_row() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    row = MagicMock(
        assistant_name=None,
        assistant_tone=None,
        assistant_custom_instructions=None,
        merchant_morning_digest_enabled=False,
    )

    with patch(
        "app.services.shop_assistant_persona_settings.settings_repo.get_or_create",
        new=AsyncMock(return_value=row),
    ):
        out = await ShopAssistantPersonaService(db).patch_settings(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            data=ShopAssistantPersonaPatch(
                assistant_name="Lan",
                assistant_tone="friendly",
            ),
        )

    assert out.assistant_name == "Lan"
    assert row.assistant_name == "Lan"
    assert row.assistant_tone == "friendly"


async def test_patch_rejects_invalid_tone() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    db = MagicMock()
    row = MagicMock(
        assistant_name=None,
        assistant_tone=None,
        assistant_custom_instructions=None,
        merchant_morning_digest_enabled=False,
    )

    with patch(
        "app.services.shop_assistant_persona_settings.settings_repo.get_or_create",
        new=AsyncMock(return_value=row),
    ):
        with pytest.raises(BadRequestError, match="Invalid assistant tone"):
            await ShopAssistantPersonaService(db).patch_settings(
                organization_id=org_id,
                minerp_tenant_id=tenant_id,
                data=ShopAssistantPersonaPatch(assistant_tone="sarcastic"),
            )
