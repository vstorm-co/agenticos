"""Request-only channel metadata stays screened and out of retained snapshots."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_harness.guardrails import GuardrailResult

from app.agents.capabilities.guardrails._capability import GuardrailsConfig, input_screen
from app.agents.manifest import RecordingModel, RunRecorder, as_payload
from app.db.models.channel_identity import ChannelIdentity
from app.services.channels.base import IncomingMessage
from app.services.channels.formatting import (
    ChannelReference,
    _history_author,
    authored_prompt,
    channel_author_references,
    screen_channel_reference,
)
from app.services.message_history import CHANNEL_AUTHOR_ID, build_message_history

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def test_editable_reference_fields_are_screened_without_screening_platform_syntax() -> None:
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id="bot",
        platform_user_id="1234567890",
        platform_chat_id="room",
        platform_display_name="classified",
        platform_username="alice@example.com",
        chat_type="group",
        message_id="group",
        text="",
    )
    reference = (
        "- Name: sk-ant-api03-ABCDEFGHIJKLMNOPQR\n- Purpose: alice@example.com\n- Topic: classified\n- Visible members: alice@example.com\n- Reported member count: 1234567890\n"
        + authored_prompt("", incoming)
    )
    screen = input_screen(
        GuardrailsConfig(
            redact_pii_in=True, redact_secrets_in=True, blocked_keywords_in="classified, group"
        )
    )
    result = screen_channel_reference(reference, screen)
    assert "sk-ant-api03-ABCDEFGHIJKLMNOPQR" not in result
    assert "classified" not in result and "alice@example.com" not in result
    assert "withheld by input guardrail" in result
    assert '"chat_type": "group"' in result and '"user_id": "1234567890"' in result
    assert "- Reported member count: 1234567890" in result
    assert screen_channel_reference(reference, None) == reference
    assert (
        screen_channel_reference("- Topic: secret", lambda text: GuardrailResult.block("blocked"))
        == "- Topic: (withheld by input guardrail)"
    )


def test_author_reference_ids_are_validated() -> None:
    assert _history_author(ModelRequest(parts=[])) is None
    for bad in [123, "not-a-uuid"]:
        with pytest.raises((TypeError, ValueError)):
            _history_author(ModelRequest(parts=[], metadata={CHANNEL_AUTHOR_ID: bad}))


async def test_history_uses_opaque_refs_and_resolves_names_only_for_the_model() -> None:
    identity_id = uuid4()
    identity = ChannelIdentity(
        id=identity_id,
        platform="slack",
        platform_user_id="U-PRIVATE",
        platform_username="alice@example.com",
        platform_display_name="Secret Name",
    )
    history = build_message_history(
        [
            {"role": "user", "content": "Earlier question", "channel_identity_id": identity_id},
            {"role": "assistant", "content": "Earlier answer"},
        ]
    )
    assert history[0].metadata == {CHANNEL_AUTHOR_ID: str(identity_id)}
    recorder = RunRecorder()
    observed = []

    def respond(messages, info):
        observed.append(messages)
        return ModelResponse(parts=[TextPart(content="ok")])

    lookup = AsyncMock(return_value={identity_id: identity})
    reference = ChannelReference(
        "- Topic: classified",
        screen=input_screen(GuardrailsConfig(redact_pii_in=True, blocked_keywords_in="classified")),
        lookup_authors=lookup,
        authors_by_timestamp=channel_author_references(history),
    )
    agent = Agent(RecordingModel(FunctionModel(respond), recorder), capabilities=[reference])
    result = await agent.run("Current question", message_history=history)
    dispatched = str(observed)
    assert "U-PRIVATE" in dispatched and "Secret Name" in dispatched
    assert "alice@example.com" not in dispatched and "classified" not in dispatched
    kept = json.dumps(as_payload(recorder), default=str)
    for private in ["U-PRIVATE", "Secret Name", "alice@example.com", "classified"]:
        assert private not in kept
    assert "Earlier question" in kept and "Current question" in kept
    assert "U-PRIVATE" not in str(result.all_messages())
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from app.services.agent_runner import PausedRunState

    parked = PausedRunState(
        messages=ModelMessagesTypeAdapter.dump_python(result.all_messages(), mode="json"),
        tool_call_ids={},
        channel_authors=reference.authors_by_timestamp,
    )
    encoded = parked.model_dump_json()
    assert "U-PRIVATE" not in encoded and "Secret Name" not in encoded
    restored = PausedRunState.model_validate_json(encoded)
    lookup.return_value = {}
    observed.clear()
    resumed = ChannelReference(
        "", authors_by_timestamp=restored.channel_authors, lookup_authors=lookup
    )
    await Agent(RecordingModel(FunctionModel(respond), recorder), capabilities=[resumed]).run(
        "After erasure", message_history=ModelMessagesTypeAdapter.validate_python(restored.messages)
    )
    assert "U-PRIVATE" not in str(observed) and "Secret Name" not in str(observed)
    lookup.assert_awaited()


async def test_resumed_current_author_is_resolved_from_the_run_identity() -> None:
    identity_id = uuid4()
    identity = ChannelIdentity(
        id=identity_id,
        platform="slack",
        platform_user_id="U-ACTIVE",
        platform_username=None,
        platform_display_name=None,
    )
    seen = []

    def respond(messages, info):
        seen.extend(messages)
        return ModelResponse(parts=[TextPart(content="ok")])

    lookup = AsyncMock(return_value={identity_id: identity})
    reference = ChannelReference("", author_identity_id=identity_id, lookup_authors=lookup)
    await Agent(FunctionModel(respond), capabilities=[reference]).run("Continue")
    assert "U-ACTIVE" in str(seen)
    assert '"display_name": null' in str(seen)
    lookup.return_value = {}
    seen.clear()
    await Agent(FunctionModel(respond), capabilities=[reference]).run("Continue")
    assert "U-ACTIVE" not in str(seen)


def test_reference_capture_rejects_ambiguous_authors_and_preserves_plain_parts() -> None:
    from pydantic_ai.messages import UserPromptPart

    from app.agents.channel_reference import ChannelReferencePart, recorded_channel_messages

    part = UserPromptPart(content="same timestamp")
    first = ModelRequest(
        parts=[SystemPromptPart(content="System guidance"), part],
        metadata={CHANNEL_AUTHOR_ID: str(uuid4())},
    )
    second = ModelRequest(parts=[part], metadata={CHANNEL_AUTHOR_ID: str(uuid4())})
    assert (
        channel_author_references(
            [ModelResponse(parts=[TextPart(content="answer")]), ModelRequest(parts=[])]
        )
        == {}
    )
    with pytest.raises(ValueError, match="Ambiguous"):
        channel_author_references([first, second])
    response = ModelResponse(parts=[TextPart(content="answer")])
    reference = ChannelReferencePart(content="private names")
    current = ModelRequest(parts=[reference, part])
    recorded = recorded_channel_messages([current, response, first])
    assert recorded[0].parts == [part] and current.parts == [reference, part]
    assert recorded[1:] == [response, first]
    assert screen_channel_reference(
        authored_prompt(
            "",
            IncomingMessage(
                platform="slack",
                bot_id="bot",
                platform_user_id="id",
                platform_chat_id="room",
                text="",
                chat_type="group",
            ),
        ),
        input_screen(GuardrailsConfig(redact_pii_in=True)),
    )


def test_history_assigns_distinct_part_timestamps_when_the_clock_does_not_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from pydantic_ai.messages import UserPromptPart

    from app.services import message_history

    same = datetime(2026, 10, 30, tzinfo=UTC)
    monkeypatch.setattr(
        message_history, "UserPromptPart", lambda **kwargs: UserPromptPart(timestamp=same, **kwargs)
    )
    ids = [uuid4(), uuid4()]
    history = build_message_history(
        [
            {"role": "user", "content": "One", "channel_identity_id": ids[0]},
            {"role": "user", "content": "Two", "channel_identity_id": ids[1]},
        ]
    )
    refs = channel_author_references(history)
    assert len(refs) == 2 and set(refs.values()) == set(ids)


async def test_streamed_author_references_are_screened_and_not_retained() -> None:
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    incoming = IncomingMessage(
        platform="slack",
        bot_id="bot",
        platform_chat_id="room",
        platform_user_id="U-STREAM-PRIVATE",
        chat_type="group",
        text="",
        platform_display_name="private@example.com",
    )
    reference = ChannelReference(
        "- Topic: confidential",
        author_context=authored_prompt("", incoming),
        screen=input_screen(
            GuardrailsConfig(redact_pii_in=True, blocked_keywords_in="confidential")
        ),
    )
    seen = []

    async def stream(messages, info):
        seen.extend(messages)
        yield "ok"

    recorder = RunRecorder()
    model = RecordingModel(FunctionModel(stream_function=stream), recorder)
    async with Agent(model, capabilities=[reference]).run_stream("Actual question") as result:
        assert await result.get_output() == "ok"
        stored = ModelMessagesTypeAdapter.dump_json(result.all_messages()).decode()
    assert "U-STREAM-PRIVATE" in str(seen)
    assert "private@example.com" not in str(seen) and "confidential" not in str(seen)
    assert "U-STREAM-PRIVATE" not in stored and "private@example.com" not in stored
    assert "U-STREAM-PRIVATE" not in json.dumps(as_payload(recorder), default=str)
