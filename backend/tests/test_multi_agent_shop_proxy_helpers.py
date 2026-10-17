"""Shop AI strangler proxy helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.multi_agent_shop_proxy import (
    _should_stream_response,
    _timeout_for_subpath,
)


def test_timeout_longer_for_llm_paths() -> None:
    assert _timeout_for_subpath("mcp/catalog") == 120.0
    assert _timeout_for_subpath("llm-generate") == 180.0
    assert _timeout_for_subpath("merchant-assistant/chat/stream") == 180.0


def test_should_stream_on_stream_suffix() -> None:
    request = MagicMock()
    request.headers = {"accept": "application/json"}
    assert _should_stream_response(request, "merchant-assistant/chat/stream") is True


def test_should_stream_on_sse_accept() -> None:
    request = MagicMock()
    request.headers = {"accept": "text/event-stream"}
    assert _should_stream_response(request, "merchant-assistant/chat") is True
