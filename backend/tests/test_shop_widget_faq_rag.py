"""B48 — widget FAQ RAG native."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.rag.models import SearchResult
from app.services.shop_widget_faq_rag import (
    _format_faq_reply,
    try_widget_faq_rag_reply,
)

pytestmark = pytest.mark.anyio


def test_format_faq_reply_dedupes() -> None:
    hits = [
        SearchResult(content="A", score=0.9, metadata={}),
        SearchResult(content="A", score=0.8, metadata={}),
        SearchResult(content="B", score=0.7, metadata={}),
    ]
    text = _format_faq_reply(hits)
    assert text is not None
    assert "A" in text
    assert "B" in text


async def test_try_widget_faq_rag_no_org(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.shop_widget_faq_rag.shop_native_widget_faq_rag_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_faq_rag.resolve_shop_tenant_kb",
        AsyncMock(return_value=None),
    )
    out = await try_widget_faq_rag_reply(
        AsyncMock(),
        tenant_id=uuid4(),
        message="cod được không?",
        kb_id=None,
    )
    assert out is None
