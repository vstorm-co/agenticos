"""OpenRouter's reasoning, sent back as it arrived and resent without it once refused.

Driven through the real `OpenRouterModel` over an `httpx2.MockTransport`, so the
wire format and Pydantic AI's error mapping are the library's own: an upgrade
that changes either fails here rather than in a run.
"""

import copy
import json
from collections.abc import Callable

import httpx2
import pytest
from pydantic_ai import Agent, ModelRetry, StructuredDict, ToolOutput
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.agents.model_resolver import ResolvedCredential, build_model
from app.agents.openrouter_model import (
    ReasoningResendOpenRouterModel,
    without_latest_reasoning,
)
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio

MODEL = "anthropic/claude-opus-5.5"
SIGNATURE = "EqQBCkYIBxgCKkDsignature"
THOUGHT = "The criterion asks for correctness; the sum is right."
REFUSAL = (
    "messages.1.content.1: `thinking` or `redacted_thinking` blocks in the latest "
    "assistant message cannot be modified. These blocks must remain as they were in "
    "the original response."
)
AZURE_REFUSAL = (
    "messages.1.content.0: Invalid `signature` in `thinking` block. "
    "The block is bound to a different conversation."
)


def _completion(message: dict[str, object], finish_reason: str = "stop") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 1,
            "model": MODEL,
            "provider": "Anthropic",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "native_finish_reason": finish_reason,
                    "message": {"role": "assistant", **message},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def _answer_call(call_id: str, verdict: str) -> dict[str, object]:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "answer", "arguments": json.dumps({"verdict": verdict})},
            }
        ],
    }


def _refused(message: str = REFUSAL) -> httpx2.Response:
    raw = json.dumps(
        {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    )
    return httpx2.Response(
        400,
        json={
            "error": {
                "code": 400,
                "message": "Provider returned error",
                "metadata": {"raw": raw, "provider_name": "Anthropic"},
            }
        },
    )


def _sse(*chunks: dict[str, object]) -> httpx2.Response:
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


def _chunk(delta: dict[str, object], finish_reason: str | None = None) -> dict[str, object]:
    return {
        "id": "gen-2",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": MODEL,
        "provider": "Anthropic",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


class OpenRouter:
    """A scripted OpenRouter: answers in order, and keeps every request body."""

    def __init__(self, *answers: httpx2.Response | Callable[[], httpx2.Response]) -> None:
        self.answers = list(answers)
        self.bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        answer = self.answers.pop(0)
        return answer() if callable(answer) else answer

    def model(self) -> ReasoningResendOpenRouterModel:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(self))
        return ReasoningResendOpenRouterModel(
            MODEL, provider=OpenRouterProvider(api_key="sk-or-test", http_client=client)
        )


def _assistant(body: dict[str, object]) -> dict[str, object]:
    messages = body["messages"]
    assert isinstance(messages, list)
    return next(m for m in reversed(messages) if m["role"] == "assistant")


def _history() -> list[ModelMessage]:
    """A judge's first answer, its reasoning signed, sent back by the schema check."""
    return [
        ModelRequest(parts=[UserPromptPart(content="Grade it.")]),
        ModelResponse(
            parts=[
                ThinkingPart(
                    content=THOUGHT,
                    signature=SIGNATURE,
                    provider_name="openrouter",
                    provider_details={
                        "format": "anthropic-claude-v1",
                        "index": 0,
                        "type": "reasoning.text",
                    },
                ),
                TextPart(content="I check correctness."),
                ToolCallPart(tool_name="answer", args={"verdict": "pass"}, tool_call_id="toolu_1"),
            ],
            model_name=MODEL,
            provider_name="openrouter",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="answer",
                    content="Name the criterion you checked.",
                    tool_call_id="toolu_1",
                    outcome="retried",
                )
            ]
        ),
    ]


def _judge(model: ReasoningResendOpenRouterModel) -> Agent[None, dict[str, object]]:
    schema = {"type": "object", "properties": {"verdict": {"type": "string"}}}
    agent = Agent(
        model,
        output_type=ToolOutput(StructuredDict(schema), name="answer", strict=False),
    )
    checked: list[dict[str, object]] = []

    @agent.output_validator
    def once(output: dict[str, object]) -> dict[str, object]:
        checked.append(output)
        if len(checked) == 1:
            raise ModelRetry("Name the criterion you checked.")
        return output

    return agent


def _first_answer() -> httpx2.Response:
    return _completion(
        {
            "content": "I check correctness.",
            "reasoning": THOUGHT,
            "reasoning_details": [
                {
                    "type": "reasoning.text",
                    "text": THOUGHT,
                    "signature": SIGNATURE,
                    "format": "anthropic-claude-v1",
                    "index": 0,
                }
            ],
            **{k: v for k, v in _answer_call("toolu_1", "pass").items() if k != "content"},
        },
        finish_reason="tool_calls",
    )


def test_openrouter_profiles_build_the_resending_model():
    credential = ResolvedCredential(
        provider="openrouter", secret=ApiKeySecret(api_key="sk-or-test")
    )

    assert isinstance(build_model(credential, MODEL), ReasoningResendOpenRouterModel)


async def test_a_retry_sends_the_reasoning_back_as_it_arrived():
    """The signed block and the call after it go back unchanged, in their order."""
    openrouter = OpenRouter(_first_answer(), _completion(_answer_call("toolu_2", "pass")))

    result = await _judge(openrouter.model()).run("Grade it.")

    assert result.output == {"verdict": "pass"}
    echoed = _assistant(openrouter.bodies[1])
    assert echoed["reasoning_details"] == [
        {
            "id": None,
            "format": "anthropic-claude-v1",
            "index": 0,
            "type": "reasoning.text",
            "text": THOUGHT,
            "signature": SIGNATURE,
        }
    ]
    assert echoed["content"] == "I check correctness."
    assert [call["id"] for call in echoed["tool_calls"]] == ["toolu_1"]


@pytest.mark.parametrize("refusal", [REFUSAL, AZURE_REFUSAL])
async def test_a_refused_retry_is_resent_without_the_reasoning(refusal: str):
    openrouter = OpenRouter(
        _first_answer(), _refused(refusal), _completion(_answer_call("toolu_2", "pass"))
    )

    result = await _judge(openrouter.model()).run("Grade it.")

    assert result.output == {"verdict": "pass"}
    assert len(openrouter.bodies) == 3
    resent = _assistant(openrouter.bodies[2])
    assert "reasoning_details" not in resent
    assert not resent.get("reasoning")
    assert resent["content"] == "I check correctness."
    assert [call["id"] for call in resent["tool_calls"]] == ["toolu_1"]
    kept = result.all_messages()[1]
    assert isinstance(kept, ModelResponse)
    assert any(
        isinstance(part, ThinkingPart) and part.signature == SIGNATURE for part in kept.parts
    )


async def test_the_resend_leaves_the_history_it_was_handed_untouched():
    openrouter = OpenRouter(_refused(), _completion({"content": "pass"}))
    messages = _history()
    before = copy.deepcopy(messages)
    objects = [id(message) for message in messages]

    await openrouter.model().request(messages, None, ModelRequestParameters())

    assert messages == before
    assert [id(message) for message in messages] == objects
    assert "reasoning_details" in _assistant(openrouter.bodies[0])
    assert "reasoning_details" not in _assistant(openrouter.bodies[1])


async def test_only_the_latest_response_loses_its_reasoning():
    earlier = _history()[1]
    messages = [*_history(), copy.deepcopy(earlier), _history()[2]]

    copied = without_latest_reasoning(messages)

    assert copied[1] is messages[1]
    latest = copied[3]
    assert isinstance(latest, ModelResponse)
    assert not any(isinstance(part, ThinkingPart) for part in latest.parts)
    assert [type(part) for part in latest.parts] == [TextPart, ToolCallPart]


async def test_a_history_without_a_response_is_copied_as_it_is():
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hi")])]

    copied = without_latest_reasoning(messages)

    assert copied == messages
    assert copied is not messages


async def test_another_refusal_is_not_resent():
    """A 400 about anything but the reasoning is the caller's to handle."""
    openrouter = OpenRouter(
        _refused("messages.1.content.0: tool_use ids must be unique"),
        _completion({"content": "never"}),
    )

    with pytest.raises(ModelHTTPError) as raised:
        await openrouter.model().request(_history(), None, ModelRequestParameters())

    assert raised.value.status_code == 400
    assert len(openrouter.bodies) == 1


async def test_a_second_refusal_is_raised_not_resent_again():
    openrouter = OpenRouter(_refused(), _refused(), _completion({"content": "never"}))

    with pytest.raises(ModelHTTPError) as raised:
        await openrouter.model().request(_history(), None, ModelRequestParameters())

    assert raised.value.status_code == 400
    assert len(openrouter.bodies) == 2


async def test_a_refused_stream_is_resent_before_its_first_event():
    openrouter = OpenRouter(
        _refused(),
        _sse(_chunk({"role": "assistant", "content": "pass"}), _chunk({}, "stop")),
    )
    messages = _history()
    before = copy.deepcopy(messages)

    async with openrouter.model().request_stream(
        messages, None, ModelRequestParameters()
    ) as stream:
        async for _ in stream:
            pass

    assert stream.get().parts == [TextPart(content="pass")]
    assert messages == before
    assert "reasoning_details" not in _assistant(openrouter.bodies[1])


async def test_a_stream_that_fails_after_its_first_event_is_not_resent():
    error = {
        "id": "gen-3",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": MODEL,
        "provider": "Anthropic",
        "error": {"code": 400, "message": REFUSAL},
        "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "error"}],
    }
    openrouter = OpenRouter(
        _sse(_chunk({"role": "assistant", "content": "Grading"}), error),
        _completion({"content": "never"}),
    )

    with pytest.raises(ModelHTTPError):
        async with openrouter.model().request_stream(
            _history(), None, ModelRequestParameters()
        ) as stream:
            async for _ in stream:
                pass

    assert len(openrouter.bodies) == 1


async def test_a_stream_refused_for_another_reason_is_not_resent():
    openrouter = OpenRouter(_refused("max_tokens: must be at most 64000"))

    with pytest.raises(ModelHTTPError):
        async with openrouter.model().request_stream(_history(), None, ModelRequestParameters()):
            pass

    assert len(openrouter.bodies) == 1
