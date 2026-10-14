"""Guardrails over a call's transcripts: detect, interrupt, log (#54)."""

from __future__ import annotations

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.services.voice.guard import WITHHELD, TranscriptGuard


def _guard(**config: object) -> TranscriptGuard:
    return TranscriptGuard.for_spec(
        AgentSpec(name="a", capabilities=[CapabilityBindingSpec(id="guardrails", config=config)])
    )


def test_a_blocked_answer_is_withheld_and_counted():
    guard = _guard(blocked_keywords_out="internal codename")
    screened = guard.screen("The internal codename is Falcon", speaker="assistant")
    assert screened.blocked and screened.text == WITHHELD and guard.hits == 1


def test_a_redacted_caller_turn_is_saved_redacted_and_not_counted():
    guard = _guard(redact_pii_in=True)
    screened = guard.screen("mail me at ann@example.com", speaker="user")
    assert not screened.blocked and "ann@example.com" not in screened.text and guard.hits == 0


def test_an_agent_without_guardrails_passes_everything():
    guard = TranscriptGuard.for_spec(AgentSpec(name="a"))
    assert guard.screen("anything", speaker="assistant").text == "anything"
    assert not guard.screens_agent


def test_an_output_edge_makes_the_agents_captions_wait_for_the_check():
    assert _guard(blocked_keywords_out="x").screens_agent
    assert not _guard(redact_pii_in=True).screens_agent


def test_an_edge_that_is_not_configured_passes_that_speaker():
    guard = _guard(redact_pii_in=True)
    assert guard.screen("ann@example.com", speaker="assistant").text == "ann@example.com"


def test_a_clean_turn_is_kept_as_said():
    guard = _guard(blocked_keywords_out="internal codename")
    screened = guard.screen("It is sunny.", speaker="assistant")
    assert (screened.text, screened.blocked, guard.hits) == ("It is sunny.", False, 0)
