"""B81 — channel AI pipeline note for strangler matrix."""

from __future__ import annotations

from app.services.shop_channel_ai_pipeline import channel_inbound_ai_pipeline_note


def test_pipeline_note_includes_widget_and_llm() -> None:
    note = channel_inbound_ai_pipeline_note()
    assert "widget-native" in note or "widget-proxy" in note
    assert "channel-LLM" in note or "multi-agent" in note or "native shop tools" in note
