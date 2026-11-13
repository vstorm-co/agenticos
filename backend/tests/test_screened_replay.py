"""Redactions survive replay, including empty replacements and legacy snapshots."""

import pytest
from pydantic_ai.messages import (
    CompactionPart,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai_harness.guardrails import GuardrailResult

from app.services.message_history import REFUSED_TURN, ModelHistory
from app.services.screened_replay import screen_history, screened_copy

pytestmark = pytest.mark.security


def test_projection_preserves_raw_audit_and_screens_the_whole_attachment_briefing():
    def redact(text: str) -> GuardrailResult:
        return GuardrailResult.replace(text.replace("SECRET", "[hidden]"))

    assert screened_copy("caption", "SECRET", redact) == "caption[hidden]"
    assert screened_copy("SECRET", None, None) is None
    assert screened_copy("fine", None, lambda text: GuardrailResult.allow()) is None
    assert screened_copy("blocked", None, lambda text: GuardrailResult.block("no")) == REFUSED_TURN


def test_legacy_history_is_screened_before_compaction_without_mutating_its_snapshot():
    user = ModelRequest(parts=[UserPromptPart("SECRET"), UserPromptPart(["image caption"])])
    answer = ModelResponse(parts=[TextPart("OK")])
    history = ModelHistory([user, answer], revision=7)
    cleaned = screen_history(history, lambda text: GuardrailResult.replace(""))
    assert isinstance(cleaned, ModelHistory)
    assert cleaned.revision == 7
    assert cleaned[0].parts[0].content == ""
    assert user.parts[0].content == "SECRET"
    assert cleaned[1] == answer
    assert screen_history(history, None) is history
    assert screen_history(None, None) is None
    assert screen_history([user], lambda text: GuardrailResult.allow()) == [user]


def test_stored_compaction_and_legacy_summary_are_screened_before_reuse():
    history = [
        ModelRequest(parts=[SystemPromptPart("Summary of previous conversation:\n\nSECRET")]),
        ModelResponse(parts=[CompactionPart("A summary carrying SECRET")]),
    ]
    cleaned = screen_history(
        history, lambda text: GuardrailResult.replace(text.replace("SECRET", "[hidden]"))
    )
    assert "SECRET" in history[0].parts[0].content
    assert all("SECRET" not in part.content for message in cleaned for part in message.parts)
