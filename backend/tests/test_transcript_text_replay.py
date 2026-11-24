"""Stored answer text must reach a model once, with its compaction anchor."""

from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, _clean_message_history
from pydantic_ai_harness.compaction import estimate_context_tokens

from app.db.models.conversation import Message
from app.schemas.conversation import MessageCreate, MessagePart
from app.services.conversation import _as_history
from app.services.message_history import build_message_history


@pytest.mark.parametrize(
    ("texts", "content", "expected"),
    [
        (["\n\nThe answer."], "\n\nThe answer.", ["\n\nThe answer."]),
        (["The answer. \t\n"], "The answer. \t\n", ["The answer. \t\n"]),
        (["\u2003The answer.\u2003"], "The answer.", ["\u2003The answer.\u2003"]),
        (["Earlier.", "Final ", "answer."], "Final answer.", ["Earlier.", "Final ", "answer."]),
        (["Before", " \n", "after"], "Before \nafter", ["Before", " \nafter"]),
        (["First.", "Second."], "First.Second.", ["First.", "Second."]),
        (["First.", "Second."], "Second.", ["First.", "Second."]),
        (["Draft."], "Final.", ["Draft.", "Final."]),
        (["Prefix answer."], "answer.", ["Prefix answer.", "answer."]),
        ([], "Legacy answer.", ["Legacy answer."]),
        ([" \n"], "Final.", ["Final."]),
        (["Partial.", ""], "Partial.", ["Partial."]),
        ([" \n", "Answer."], "Answer.", [" \nAnswer."]),
        ([" \n", "\t", "Answer."], "Answer.", [" \n\tAnswer."]),
        (["Prefix", " \n", "Answer."], "Answer.", ["Prefix", " \nAnswer."]),
        (["A"] * 20_000, "A" * 20_000, ["A"] * 20_000),
        ([" " * 200] * 20_000 + ["A"], "A", [" " * 4_000_000 + "A"]),
    ],
)
def test_stored_answer_is_replayed_once(
    texts: list[str], content: str, expected: list[str]
) -> None:
    stored = MessageCreate(
        role="assistant",
        content=content,
        parts=[MessagePart(type="thinking", text="Reasoning.")]
        + [MessagePart(type="text", text=text) for text in texts],
    )
    row = Message(
        id=uuid4(),
        role=stored.role,
        content=stored.content,
        parts=[part.model_dump(exclude_none=True) for part in stored.parts or []],
        guardrail_refused=False,
        context_used_tokens=56_000,
    )
    replay = _as_history([row], None)
    assert [entry["content"] for entry in replay] == expected
    model_history = _clean_message_history(build_message_history(replay))
    assert [
        part.content
        for message in model_history
        for part in message.parts
        if isinstance(part, TextPart)
    ] == expected
    assert estimate_context_tokens(model_history) >= 56_000


def test_answer_keeps_human_reply_order_and_anchors_the_final_response_group() -> None:
    row = Message(
        id=uuid4(),
        role="assistant",
        content="Final answer.",
        parts=[
            {"type": "text", "text": "Choose."},
            {"type": "ask_user", "question": "Which?", "answer": "A"},
            {"type": "text", "text": "Final "},
            {"type": "text", "text": "answer."},
        ],
        guardrail_refused=False,
        context_used_tokens=56_000,
    )
    replay = _as_history([row], None)
    assert [(entry["role"], entry["content"]) for entry in replay] == [
        ("assistant", "Choose."),
        ("user", "Question: Which?\nAnswer: A"),
        ("assistant", "Final "),
        ("assistant", "answer."),
    ]
    model_history = _clean_message_history(build_message_history(replay))
    assert isinstance(model_history[-1], ModelResponse)
    assert model_history[-1].usage.input_tokens == 56_000
    assert estimate_context_tokens(model_history) >= 56_000


def test_a_turn_ending_with_a_human_reply_keeps_its_last_answer_anchor() -> None:
    row = Message(
        id=uuid4(),
        role="assistant",
        content="Choose.",
        parts=[
            {"type": "text", "text": "Choose."},
            {"type": "ask_user", "question": "Which?", "answer": "A"},
        ],
        guardrail_refused=False,
        context_used_tokens=56_000,
    )
    history = _clean_message_history(build_message_history(_as_history([row], None)))
    assert isinstance(history[0], ModelResponse)
    assert history[0].usage.input_tokens == 56_000
    assert estimate_context_tokens(history) >= 56_000


def test_an_empty_legacy_answer_adds_no_model_message_or_token_anchor() -> None:
    row = Message(
        id=uuid4(),
        role="assistant",
        content="",
        parts=None,
        guardrail_refused=False,
        context_used_tokens=56_000,
    )
    assert build_message_history(_as_history([row], None)) == []


@pytest.mark.parametrize("has_text", [True, False])
def test_blank_fragments_do_not_cross_a_human_reply(has_text: bool) -> None:
    row = Message(
        id=uuid4(),
        role="assistant",
        content="Before. \nAfter." if has_text else "After.",
        parts=([{"type": "text", "text": "Before."}] if has_text else [])
        + [
            {"type": "text", "text": " \n"},
            {"type": "ask_user", "question": "Which?", "answer": "A"},
            {"type": "text", "text": "After."},
            {"type": "text", "text": " \n"},
        ],
        guardrail_refused=False,
    )
    replay = _as_history([row], None)
    expected = (["Before. \n"] if has_text else []) + ["Question: Which?\nAnswer: A", "After. \n"]
    assert [entry["content"] for entry in replay] == expected


def test_a_wholly_blank_timeline_is_not_sent_as_an_empty_model_response() -> None:
    row = Message(
        id=uuid4(),
        role="assistant",
        content="",
        parts=[{"type": "text", "text": " \n"}],
        guardrail_refused=False,
    )
    assert _as_history([row], None) == []
