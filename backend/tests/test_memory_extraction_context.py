"""Human evidence survives long answers; remote results never become human assertions."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.db.models.conversation import ToolCall
from app.services.memory.extraction import (
    MAX_TRANSCRIPT_CHARS,
    ExtractionTurn,
    answered_question_turns,
    transcript_for_extraction,
)


def question(**updates: object) -> ToolCall:
    fields: dict[str, object] = {
        "tool_id": "ask_user_question",
        "presentation_kind": None,
        "mcp_connection_id": None,
        "status": "completed",
        "result": json.dumps({"Format": ["ISO dates"]}),
        "args": {"questions": [{"header": "Format", "question": "Future report dates?"}]},
    }
    fields.update(updates)
    return ToolCall(**fields)


def test_a_long_assistant_answer_cannot_displace_the_user_preference() -> None:
    preference = "For future reports use ISO dates and put the executive summary first."
    turns = transcript_for_extraction(
        [
            ("system", "Never human evidence"),
            ("user", preference),
            ("assistant", "long output " * 2000),
            ("user", "   "),
        ]
    )
    assert turns[0] == {"role": "user", "text": preference}
    assert turns[1]["role"] == "assistant"
    assert len(json.dumps(turns, ensure_ascii=False)) <= MAX_TRANSCRIPT_CHARS


def test_recent_human_corrections_take_precedence_without_assistant_starvation() -> None:
    turns = transcript_for_extraction(
        [
            ("user", "An older fact"),
            ("user", "x" * MAX_TRANSCRIPT_CHARS + "Final human correction"),
            ("assistant", "This cannot evict the correction"),
        ]
    )
    assert len(turns) == 1
    assert turns[0]["role"] == "user"
    assert turns[0]["text"].endswith("Final human correction")
    assert "An older fact" not in turns[0]["text"]
    assert transcript_for_extraction([]) == []


def test_only_submitted_values_become_human_evidence_not_question_options() -> None:
    assert answered_question_turns([question()]) == [
        ("assistant", "Future report dates?"),
        ("user", "ISO dates"),
    ]


@pytest.mark.parametrize(
    "updates",
    [
        {"tool_id": None, "tool_name": "ask_user_question"},
        {"presentation_kind": "generic"},
        {"mcp_connection_id": uuid4()},
        {"status": "awaiting_answer"},
        {"result": None},
        {"result": "not json"},
        {"result": '"declined"'},
        {"result": "{}"},
        {"args": {}},
        {"args": {"questions": [42]}},
        {"args": {"questions": [{"header": 42, "question": "Who?"}]}},
        {"result": '{"Format":[42]}'},
        {"result": '{"Format":[" "]}'},
    ],
)
def test_unattributed_remote_failed_or_declined_answers_are_not_assertions(
    updates: dict[str, object],
) -> None:
    assert answered_question_turns([question(**updates)]) == []


def test_memory_extraction_preserves_event_dates_and_question_answer_linkage() -> None:
    at = datetime(2026, 11, 22, 23, 30, tzinfo=UTC)
    turns = transcript_for_extraction(
        [
            ExtractionTurn("user", "From next month, use ISO dates.", "message:1", at),
            ExtractionTurn("assistant", "Future report dates?", "receipt:2", at, "question"),
            ExtractionTurn("user", "ISO dates", "receipt:2", at, "authenticated_answer"),
        ]
    )
    assert turns[0]["occurred_at"] == "2026-11-22T23:30:00+00:00"
    assert turns[0]["source_id"] == "message:1"
    assert turns[1]["source_id"] == turns[2]["source_id"] == "receipt:2"
    assert turns[1]["kind"] == "question"
    assert turns[2]["kind"] == "authenticated_answer"
    assert turns[2]["text"] == "ISO dates"
    assert "excerpt" not in turns[0]


def test_memory_extraction_marks_partial_text_instead_of_claiming_complete_context() -> None:
    at = datetime(2026, 11, 22, tzinfo=UTC)
    turns = transcript_for_extraction([ExtractionTurn("user", "prefix" * 2000, "message:1", at)])
    assert turns[0]["excerpt"] == "tail"
    assert turns[0]["source_id"] == "message:1"


@pytest.mark.security
def test_dated_short_turns_include_provenance_and_json_overhead_in_the_budget() -> None:
    at = datetime(2026, 11, 22, tzinfo=UTC)
    turns = transcript_for_extraction(
        [ExtractionTurn("user", '"\\\nż', f"message:{index}", at) for index in range(500)]
    )
    assert len(json.dumps(turns, ensure_ascii=False)) <= MAX_TRANSCRIPT_CHARS
    assert turns[-1]["source_id"] == "message:499"
    assert len(turns) < 500
    assert all(turn["occurred_at"] == at.isoformat() for turn in turns)


@pytest.mark.security
@pytest.mark.parametrize("limit", [2, 30, 49, 50, 51, 80])
def test_json_escaping_and_excerpt_metadata_never_exceed_the_available_budget(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    monkeypatch.setattr("app.services.memory.extraction.MAX_TRANSCRIPT_CHARS", limit)
    turns = transcript_for_extraction([("user", '"' * 100)])
    assert len(json.dumps(turns, ensure_ascii=False)) <= limit
    if turns:
        assert turns[0]["text"]
        assert turns[0]["excerpt"] == "tail"


@pytest.mark.security
def test_a_source_identifier_that_exceeds_the_budget_is_not_truncated() -> None:
    at = datetime(2026, 11, 22, tzinfo=UTC)
    assert (
        transcript_for_extraction(
            [ExtractionTurn("user", "Keep this fact", "x" * MAX_TRANSCRIPT_CHARS, at)]
        )
        == []
    )
