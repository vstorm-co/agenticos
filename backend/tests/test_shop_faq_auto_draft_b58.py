"""B58 — FAQ settings threshold + auto-draft scheduling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_faq_suggestion import ShopFaqSuggestionService, _schedule_auto_draft_task

pytestmark = pytest.mark.anyio


async def test_maybe_enqueue_auto_draft_when_threshold_met() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    suggestion_id = uuid4()
    suggestion = MagicMock(
        id=suggestion_id,
        status="pending",
        suggested_answer=None,
        occurrence_count=3,
    )
    settings = MagicMock(auto_draft_faq_min_occurrences=3)

    db = AsyncMock()
    with (
        patch(
            "app.services.shop_faq_suggestion.shop_ai_settings_repo.get",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.shop_faq_suggestion._schedule_auto_draft_task",
        ) as schedule_mock,
    ):
        await ShopFaqSuggestionService(db)._maybe_enqueue_auto_draft(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            kb_id=kb_id,
            suggestion=suggestion,
        )

    schedule_mock.assert_called_once_with(
        db,
        organization_id=org_id,
        minerp_tenant_id=tenant_id,
        kb_id=kb_id,
        suggestion_id=suggestion_id,
    )


async def test_maybe_enqueue_skips_when_threshold_disabled() -> None:
    suggestion = MagicMock(
        id=uuid4(),
        status="pending",
        suggested_answer=None,
        occurrence_count=5,
    )
    settings = MagicMock(auto_draft_faq_min_occurrences=0)

    db = AsyncMock()
    with (
        patch(
            "app.services.shop_faq_suggestion.shop_ai_settings_repo.get",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.shop_faq_suggestion._schedule_auto_draft_task",
        ) as schedule_mock,
    ):
        await ShopFaqSuggestionService(db)._maybe_enqueue_auto_draft(
            organization_id=uuid4(),
            minerp_tenant_id=uuid4(),
            kb_id=uuid4(),
            suggestion=suggestion,
        )

    schedule_mock.assert_not_called()


async def test_auto_draft_pending_suggestion_writes_answer() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    suggestion_id = uuid4()
    kb = MagicMock(id=kb_id, name="FAQ Shop", organization_id=org_id)
    suggestion = MagicMock(
        id=suggestion_id,
        status="pending",
        suggested_answer=None,
        occurrence_count=3,
        question_text="Giao hàng bao lâu?",
    )
    settings = MagicMock(auto_draft_faq_min_occurrences=3)

    db = AsyncMock()
    svc = ShopFaqSuggestionService(db)
    with (
        patch.object(svc, "_require_faq_kb", new=AsyncMock(return_value=kb)),
        patch.object(svc, "_get_or_404", new=AsyncMock(return_value=suggestion)),
        patch(
            "app.services.shop_faq_suggestion.shop_ai_settings_repo.get",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.shop_faq_suggestion.retrieve_faq_rag_draft_text",
            new=AsyncMock(return_value="Giao trong 3–5 ngày làm việc."),
        ),
        patch(
            "app.services.shop_faq_suggestion.suggestion_repo.set_suggested_answer",
            new=AsyncMock(),
        ) as set_answer_mock,
    ):
        drafted = await svc.auto_draft_pending_suggestion(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            kb_id=kb_id,
            suggestion_id=suggestion_id,
        )

    assert drafted is True
    set_answer_mock.assert_awaited_once()


async def test_schedule_auto_draft_uses_spawn_after_commit() -> None:
    session = MagicMock()
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    suggestion_id = uuid4()

    with patch(
        "app.services.shop_faq_suggestion.spawn_after_commit",
    ) as spawn_mock:
        _schedule_auto_draft_task(
            session,
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            kb_id=kb_id,
            suggestion_id=suggestion_id,
        )

    spawn_mock.assert_called_once()
    assert spawn_mock.call_args.args[0] is session
    assert spawn_mock.call_args.kwargs["name"] == f"shop_faq_auto_draft:{suggestion_id}"
