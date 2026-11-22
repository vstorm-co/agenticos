"""Human evidence survives long answers; remote results never become human assertions."""

import json
from uuid import uuid4

import pytest

from app.db.models.conversation import ToolCall
from app.services.memory.extraction import (
    MAX_TRANSCRIPT_CHARS,
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
    assert sum(len(turn["text"]) + 32 for turn in turns) <= MAX_TRANSCRIPT_CHARS


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
