"""B61 — widget chat quality report."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_widget_quality import ShopWidgetQualityService

pytestmark = pytest.mark.anyio


async def test_build_report_collects_weak_replies_and_faq_gaps() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    conv_id = uuid4()
    now = datetime.now(UTC)

    weak_assistant = MagicMock(
        id=uuid4(),
        conversation_id=conv_id,
        role="assistant",
        content="Không tìm thấy sản phẩm phù hợp.",
        created_at=now,
    )

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    weak_result = MagicMock()
    weak_result.scalars.return_value.all.return_value = [weak_assistant]
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = "Shop giao bao lâu?"

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, weak_result, user_result])

    kb = MagicMock(id=uuid4(), name="FAQ Shop")
    suggestion = MagicMock(
        id=uuid4(),
        question_text="Giao hàng bao lâu?",
        occurrence_count=4,
        suggested_answer=None,
        last_seen_at=now,
    )

    with (
        patch(
            "app.services.shop_widget_quality.knowledge_base_repo.list_org_scoped",
            new=AsyncMock(return_value=[kb]),
        ),
        patch(
            "app.services.shop_widget_quality.suggestion_repo.list_for_kb",
            new=AsyncMock(return_value=[suggestion]),
        ),
    ):
        report = await ShopWidgetQualityService(db).build_report(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
        )

    assert report.widget_conversation_count == 1
    assert len(report.weak_replies) == 1
    assert report.weak_replies[0].user_message == "Shop giao bao lâu?"
    assert len(report.faq_gaps) == 1
    assert report.faq_gaps[0].occurrence_count == 4
