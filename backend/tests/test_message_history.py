"""Rebuilding a conversation into what a model reads.

Two things are pinned here. The empty turn: a caption-less file is recorded as an
empty user row so the file has something to hang off; the file's bytes are not in
this history, so the row reconstructs to an empty text part - which Anthropic
rejects with a 400, taking down every turn after the photo.

And the size of the request a replayed answer came out of, which is what makes
compaction fire at all. The
estimator anchors on the most recent response carrying provider usage and
estimates only what came after it; with nothing to anchor on it counts characters,
and a real agent here measured 9 tokens where the provider had charged for 3,859.
A trigger reading that never fires, however full the window actually is.
"""

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai_harness.compaction import estimate_context_tokens

from app.services.message_history import build_message_history


def test_a_row_with_text_becomes_a_part_of_the_matching_kind() -> None:
    history = build_message_history(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    )

    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], TextPart)


def test_an_empty_row_is_dropped_rather_than_sent_as_an_empty_part() -> None:
    history = build_message_history(
        [
            {"role": "user", "content": ""},
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "the real question"},
        ]
    )

    assert len(history) == 1
    assert history[0].parts[0].content == "the real question"


def test_an_answer_is_replayed_with_what_the_provider_charged_for_it() -> None:
    history = build_message_history(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello", "context_used_tokens": 3_843},
        ]
    )

    answer = history[1]
    assert isinstance(answer, ModelResponse)
    assert answer.usage.input_tokens == 3_843


def test_a_run_s_whole_bill_is_not_mistaken_for_one_request() -> None:
    """`input_tokens` on the row is every request of the turn summed; the anchor
    is a statement about one. Read from there, a hundred-step tool loop would
    replay as several times its own size and compact a history that fits."""
    history = build_message_history(
        [{"role": "assistant", "content": "hello", "input_tokens": 90_000}]  # type: ignore[typeddict-unknown-key]
    )

    answer = history[0]
    assert isinstance(answer, ModelResponse)
    assert answer.usage.input_tokens == 0


def test_the_replayed_cost_is_what_the_compaction_trigger_then_measures() -> None:
    """The whole reason the usage is carried: instructions and tool schemas are
    inside the provider's number and outside a character count, so a history
    replayed as bare text reads as a few tokens whatever it really cost."""
    rows = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "context_used_tokens": 3_843},
        {"role": "user", "content": "and again"},
    ]

    anchored = estimate_context_tokens(build_message_history(rows))
    as_text = estimate_context_tokens(
        build_message_history([{"role": row["role"], "content": row["content"]} for row in rows])
    )

    assert anchored > 3_800
    assert as_text < 100


def test_an_answer_nobody_measured_is_replayed_without_a_size() -> None:
    """A turn from before the column existed, or a run that reached no model. A
    zeroed usage is passed over by the estimator rather than anchored on, which is
    the honest reading: not a request that cost nothing."""
    history = build_message_history([{"role": "assistant", "content": "hello"}])

    answer = history[0]
    assert isinstance(answer, ModelResponse)
    assert answer.usage.input_tokens == 0


def test_checkpoint_keeps_a_bounded_suffix_and_expires_evicted_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.messages import ToolSearchCallPart, ToolSearchReturnPart

    from app.services import message_history

    messages = [
        ModelResponse(
            parts=[ToolSearchCallPart(args={"queries": ["lookup"]}, tool_call_id="search")]
        ),
        ModelRequest(
            parts=[
                ToolSearchReturnPart(
                    content={"discovered_tools": [{"name": "lookup"}]}, tool_call_id="search"
                )
            ]
        ),
        ModelResponse(parts=[TextPart("Found it")]),
        ModelRequest(parts=[UserPromptPart("Hello")]),
        ModelResponse(parts=[TextPart("Hi")]),
    ]
    monkeypatch.setattr(message_history, "MODEL_HISTORY_MESSAGES", 3)
    bounded = message_history.bounded_model_history(messages)
    assert len(bounded) == 3
    assert bounded[0].parts[0].content == message_history.HISTORY_TRIMMED
    assert bounded[1:] == messages[-2:]
    assert not any(
        isinstance(part, ToolSearchReturnPart) for message in bounded for part in message.parts
    )


def test_a_byte_limit_does_not_leave_orphaned_parallel_tool_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolCallPart, ToolReturnPart

    from app.services import message_history

    messages = [
        ModelResponse(
            parts=[
                ToolCallPart("large", {"x": "漢" * 2000}, tool_call_id="a"),
                ToolCallPart("small", {}, tool_call_id="b"),
            ]
        ),
        ModelRequest(parts=[ToolReturnPart("large", "one", tool_call_id="a")]),
        ModelRequest(parts=[ToolReturnPart("small", "two", tool_call_id="b")]),
        ModelResponse(parts=[TextPart("Done")]),
    ]
    monkeypatch.setattr(message_history, "MODEL_HISTORY_BYTES", 2000)
    bounded = message_history.bounded_model_history(messages)
    assert bounded[1:] == messages[-1:]
    assert len(ModelMessagesTypeAdapter.dump_json(bounded)) <= 2000
    assert len(messages) == 4


def test_an_oversized_final_message_leaves_an_explicit_omission_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import message_history

    monkeypatch.setattr(message_history, "MODEL_HISTORY_BYTES", 1500)
    bounded = message_history.bounded_model_history([ModelResponse(parts=[TextPart("x" * 5000)])])
    assert len(bounded) == 1
    assert bounded[0].parts[0].content == message_history.HISTORY_TRIMMED


def test_checkpoint_discards_standing_system_prompts_but_keeps_legacy_summaries() -> None:
    from pydantic_ai.messages import SystemPromptPart

    from app.services.message_history import history_for_storage

    history = history_for_storage(
        [
            ModelRequest(parts=[SystemPromptPart("OLD_INSTRUCTIONS")]),
            ModelRequest(
                parts=[
                    SystemPromptPart("Summary of previous conversation:\n\nThey found a record.")
                ]
            ),
            ModelRequest(parts=[SystemPromptPart("Old reminder"), UserPromptPart("Continue")]),
        ]
    )
    assert len(history) == 2
    assert history[0].parts[0].content.startswith("Summary of previous conversation:")
    assert history[1].parts == [history[1].parts[0]]
    assert isinstance(history[1].parts[0], UserPromptPart)
