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

    from app.services.message_history import without_standing_instructions

    history = without_standing_instructions(
        [
            *build_message_history(
                [
                    {"role": "system", "content": "OLD_INSTRUCTIONS"},
                    {
                        "role": "system",
                        "content": "Summary of previous conversation:\n\nThey found a record.",
                    },
                ]
            ),
            ModelRequest(parts=[SystemPromptPart("Old reminder"), UserPromptPart("Continue")]),
        ]
    )
    assert len(history) == 2
    assert history[0].parts[0].content.startswith("Summary of previous conversation:")
    assert history[1].parts == [history[1].parts[0]]
    assert isinstance(history[1].parts[0], UserPromptPart)


@pytest.mark.parametrize("parts", [None, ["unrecognized-legacy-part"]])
def test_bounding_a_legacy_checkpoint_does_not_reinterpret_invalid_parts(parts) -> None:
    from app.services import message_history

    oversized = {
        "kind": "response",
        "parts": [{"part_kind": "text", "content": "x" * (3 * 1024 * 1024)}],
    }
    legacy = {"kind": "request", "parts": parts}
    bounded = message_history.bounded_stored_history([oversized, legacy])
    assert bounded[1:] == [legacy]
    assert bounded[0]["parts"][0]["content"] == message_history.HISTORY_TRIMMED


def test_repeated_instructions_do_not_evict_tool_evidence_from_a_checkpoint() -> None:
    from pydantic_ai.messages import (
        ModelMessage,
        ModelMessagesTypeAdapter,
        ToolCallPart,
        ToolReturnPart,
    )

    from app.agents.ephemeral_media import dump_messages
    from app.services.message_history import (
        MODEL_HISTORY_BYTES,
        bounded_stored_history,
        without_standing_instructions,
    )

    instructions = "standing instructions " * 6000
    messages: list[ModelMessage] = []
    for index in range(20):
        messages.append(
            ModelRequest(
                parts=[UserPromptPart("Find the record")]
                if index == 0
                else [
                    ToolReturnPart("lookup", f"Evidence {index}", tool_call_id=f"call-{index - 1}")
                ],
                instructions=instructions,
            )
        )
        messages.append(
            ModelResponse(
                parts=[ToolCallPart("lookup", {"index": index}, tool_call_id=f"call-{index}")]
                if index < 19
                else [TextPart("Done")]
            )
        )

    assert len(ModelMessagesTypeAdapter.dump_json(messages)) > MODEL_HISTORY_BYTES
    assert len(bounded_stored_history(dump_messages(messages))) < len(messages)
    cleaned = without_standing_instructions(messages)
    checkpoint = bounded_stored_history(dump_messages(cleaned))
    assert len(checkpoint) == len(messages)
    assert len(ModelMessagesTypeAdapter.dump_json(cleaned)) < MODEL_HISTORY_BYTES
    restored = ModelMessagesTypeAdapter.validate_python(checkpoint)
    assert [message.parts for message in restored] == [message.parts for message in messages]
    assert all(
        message.instructions is None for message in restored if isinstance(message, ModelRequest)
    )
    assert all(
        message.instructions == instructions
        for message in messages
        if isinstance(message, ModelRequest)
    )


def test_checkpoint_removes_sdk_instruction_parts_without_mutating_the_request() -> None:
    from pydantic_ai.messages import InstructionBaselinePart, InstructionDeltaPart, InstructionPart

    from app.services.message_history import without_standing_instructions

    standing = [
        InstructionBaselinePart(instructions=[InstructionPart("Old baseline")]),
        InstructionDeltaPart(id=None, content="Old replacement"),
        InstructionDeltaPart(id=None, content=None),
    ]
    prompt = UserPromptPart("Continue")
    request = ModelRequest(
        parts=[*standing, prompt],
        instructions="Old rendered instructions",
        metadata={"trace": "kept"},
    )
    cleaned = without_standing_instructions([ModelRequest(parts=standing), request])
    assert len(cleaned) == 1
    assert isinstance(cleaned[0], ModelRequest)
    assert cleaned[0].parts == [prompt]
    assert cleaned[0].instructions is None
    assert cleaned[0].metadata == request.metadata
    assert cleaned[0].timestamp == request.timestamp
    assert request.parts == [*standing, prompt]
    assert request.instructions == "Old rendered instructions"


def test_stored_instruction_cleaning_preserves_media_metadata_and_legacy_summaries() -> None:
    from pydantic import JsonValue

    from app.services.message_history import without_stored_standing_instructions

    media: dict[str, JsonValue] = {
        "part_kind": "user-prompt",
        "content": {"ref": "media+sha256://image"},
    }
    summary: dict[str, JsonValue] = {
        "part_kind": "system-prompt",
        "content": "Summary of previous conversation:\n\nEvidence",
    }
    stored: list[dict[str, JsonValue]] = [
        {"kind": "request", "parts": [{"part_kind": "instruction-baseline"}]},
        {
            "kind": "request",
            "instructions": "standing",
            "metadata": {"author": "kept"},
            "parts": [
                {"part_kind": "instruction-delta"},
                {"part_kind": "system-prompt", "content": "standing"},
                summary,
                media,
            ],
        },
        {"kind": "response", "parts": [{"part_kind": "text", "content": "answer"}]},
        {"kind": "request", "parts": "invalid"},
        {"kind": "request", "parts": [None, {"part_kind": "system-prompt", "content": 1}]},
    ]
    cleaned = without_stored_standing_instructions(stored)
    assert len(cleaned) == 4
    assert cleaned[0] == {
        "kind": "request",
        "instructions": None,
        "metadata": {"author": "kept"},
        "parts": [summary, media],
    }
    assert cleaned[1:3] == stored[2:4]
    assert cleaned[3] == {**stored[4], "instructions": None}
    assert stored[1]["instructions"] == "standing"
