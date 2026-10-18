"""B76 — Zalo OAuth refresh beat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_zalo_oauth_flow import refresh_expiring_shop_zalo_oauth_tokens

pytestmark = pytest.mark.anyio


async def test_refresh_expiring_tokens_counts_ok() -> None:
    db = MagicMock()
    bot = MagicMock(id=uuid4())
    with (
        patch(
            "app.repositories.channel_bot_repo.list_zalo_oauth_expiring",
            new=AsyncMock(return_value=[bot]),
        ),
        patch(
            "app.services.shop_zalo_oauth_flow.refresh_shop_zalo_oauth_bot",
            new=AsyncMock(),
        ),
    ):
        out = await refresh_expiring_shop_zalo_oauth_tokens(db)
    assert out == {"refreshed": 1, "failed": 0}
