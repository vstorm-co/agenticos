"""B57 — FAQ suggestion dismiss/accept/draft and entry accept path."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.services.shop_faq_suggestion import ShopFaqSuggestionService

pytestmark = pytest.mark.anyio


async def test_dismiss_pending_suggestion() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    suggestion_id = uuid4()
    now = datetime.now(UTC)
    kb = MagicMock(id=kb_id, name="Shop FAQ", organization_id=org_id)
    suggestion = MagicMock(
        id=suggestion_id,
        knowledge_base_id=kb_id,
        question_text="Giao hàng bao lâu?",
        occurrence_count=2,
        source="widget",
        status="pending",
        suggested_answer=None,
        suggested_answer_auto=False,
        suggested_answer_at=None,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )

    db = AsyncMock()
    with (
        patch(
            "app.services.shop_faq_suggestion.knowledge_base_repo.get_by_id",
            new=AsyncMock(return_value=kb),
        ),
        patch(
            "app.services.shop_faq_suggestion.suggestion_repo.get_by_id",
            new=AsyncMock(return_value=suggestion),
        ),
        patch(
            "app.services.shop_faq_suggestion.suggestion_repo.update_status",
            new=AsyncMock(return_value=suggestion),
        ) as update_mock,
    ):
        result = await ShopFaqSuggestionService(db).dismiss(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            kb_id=kb_id,
            suggestion_id=suggestion_id,
        )

    update_mock.assert_awaited_once()
    assert result.id == suggestion_id
    assert result.tenant_id == tenant_id


async def test_accept_creates_entry_and_marks_suggestion() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    suggestion_id = uuid4()
    now = datetime.now(UTC)
    kb = MagicMock(id=kb_id, name="Shop FAQ", organization_id=org_id)
    suggestion = MagicMock(
        id=suggestion_id,
        knowledge_base_id=kb_id,
        question_text="Đổi trả trong bao nhiêu ngày?",
        occurrence_count=1,
        source="inbox",
        status="pending",
        suggested_answer="Trong 7 ngày kể từ khi nhận hàng.",
        suggested_answer_auto=False,
        suggested_answer_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    entry_read = MagicMock(id=uuid4(), question=suggestion.question_text)

    db = AsyncMock()
    with (
        patch(
            "app.services.shop_faq_suggestion.knowledge_base_repo.get_by_id",
            new=AsyncMock(return_value=kb),
        ),
        patch(
            "app.services.shop_faq_suggestion.suggestion_repo.get_by_id",
            new=AsyncMock(return_value=suggestion),
        ),
        patch.object(
            ShopFaqSuggestionService,
            "_create_faq_entry_for_accept",
            new=AsyncMock(return_value=entry_read),
        ) as create_mock,
        patch(
            "app.services.shop_faq_suggestion.suggestion_repo.update_status",
            new=AsyncMock(return_value=suggestion),
        ) as update_mock,
    ):
        from app.schemas.shop_faq import ShopFaqSuggestionAccept

        result = await ShopFaqSuggestionService(db).accept(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            kb_id=kb_id,
            suggestion_id=suggestion_id,
            data=ShopFaqSuggestionAccept(is_published=True),
        )

    create_mock.assert_awaited_once()
    update_mock.assert_awaited_once()
    assert result == entry_read


async def test_draft_answer_requires_rag_excerpt() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    suggestion_id = uuid4()
    now = datetime.now(UTC)
    kb = MagicMock(id=kb_id, name="Shop FAQ", organization_id=org_id)
    suggestion = MagicMock(
        id=suggestion_id,
        knowledge_base_id=kb_id,
        question_text="Có ship COD không?",
        occurrence_count=1,
        source="widget",
        status="pending",
        suggested_answer=None,
        suggested_answer_auto=False,
        suggested_answer_at=None,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )

    db = AsyncMock()
    with (
        patch(
            "app.services.shop_faq_suggestion.knowledge_base_repo.get_by_id",
            new=AsyncMock(return_value=kb),
        ),
        patch(
            "app.services.shop_faq_suggestion.suggestion_repo.get_by_id",
            new=AsyncMock(return_value=suggestion),
        ),
        patch(
            "app.services.shop_faq_suggestion.retrieve_faq_rag_draft_text",
            new=AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(BadRequestError, match="No knowledge base excerpts"):
            await ShopFaqSuggestionService(db).draft_answer(
                organization_id=org_id,
                minerp_tenant_id=tenant_id,
                kb_id=kb_id,
                suggestion_id=suggestion_id,
            )
