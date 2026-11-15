"""Native Claude decisions must use the same tool and approval loop as every agent."""

import asyncio
import json
from io import BytesIO
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.capabilities import Instrumentation, Thinking
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError
from pydantic_ai.messages import (
    BinaryContent,
    CompactionPart,
    ImageUrl,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    RetryFeedbackPart,
    RetryInfo,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters, override_allow_model_requests
from pydantic_ai.native_tools import WebSearchTool
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDefinition,
    ToolReturn,
)
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import load_builtins
from app.agents.capabilities.approval import ApprovalGranted, ApprovalPending
from app.agents.claude_subscription import ClaudeSubscriptionModelClient
from app.agents.ephemeral_media import dump_messages, ephemeral_image
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.claude_subscription import CLAUDE_SUBSCRIPTION_PROVIDER, ClaudeSubscriptionOwner
from app.core.secret_kinds import NoSecret
from app.services.claude_subscription import ClaudeInference, ClaudeSubscriptionRuntime

pytestmark = pytest.mark.anyio


def _owner():
    return ClaudeSubscriptionOwner(organization_id=uuid4(), user_id=uuid4())


def _reply(text=None, *, calls=()):
    return ClaudeInference.model_validate(
        {
            "structured_output": {
                "text": text,
                "tool_calls": [
                    {"name": name, "arguments_json": json.dumps(args)} for name, args in calls
                ],
            },
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
            },
            "model": "claude-sonnet-4-6",
        }
    )


def _model(*replies):
    runtime = AsyncMock(spec=ClaudeSubscriptionRuntime)
    runtime.infer.side_effect = (
        replies if replies else AssertionError("Unexpected inference request")
    )
    return ClaudeSubscriptionModelClient("sonnet", owner=_owner(), runtime=runtime), runtime


def _prompt(runtime, index=-1):
    prompt = runtime.infer.await_args_list[index].kwargs["prompt"]
    return json.loads(prompt[prompt.index('{"instructions"') :])


@pytest.mark.parametrize("streamed", [False, True])
async def test_real_agent_executes_an_application_tool_and_sends_its_result(streamed):
    model, runtime = _model(
        _reply(calls=[("find_contact", {"name": "Sam"})]), _reply("Sam works at T3.")
    )
    calls = []

    def find_contact(name: str) -> str:
        """Find a contact's organization."""
        calls.append(name)
        return "Sam: T3"

    agent = Agent(model, instructions="Use contacts to answer.", tools=[find_contact])
    if streamed:
        async with agent.run_stream("Where does Sam work?") as result:
            assert await result.get_output() == "Sam works at T3."
    else:
        result = await agent.run("Where does Sam work?")
        assert result.output == "Sam works at T3."
    assert calls == ["Sam"]
    assert runtime.infer.await_count == 2
    first, second = _prompt(runtime, 0), _prompt(runtime, 1)
    assert "Use contacts to answer." in first["instructions"]
    assert [tool["name"] for tool in first["available_tools"]] == ["find_contact"]
    assert any(
        part["role"] == "tool" and part["text"] == "Sam: T3" for part in second["conversation"]
    )
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 8
    assert result.usage.cache_read_tokens == 6
    assert result.usage.cache_write_tokens == 4


@pytest.mark.security
async def test_factory_approval_parks_then_resumes_the_real_tool_once():
    load_builtins()
    owner = _owner()
    runtime = AsyncMock(spec=ClaudeSubscriptionRuntime)
    runtime.infer.side_effect = [
        _reply(calls=[("update_contact", {"name": "Sam"})]),
        _reply("Contact updated."),
    ]
    model_spec = ModelRequestSpec(
        profile_id=uuid4(),
        label="My Claude",
        provider=CLAUDE_SUBSCRIPTION_PROVIDER,
        model="sonnet",
        params={},
        fallbacks=[],
        credential=ResolvedCredential(
            provider=CLAUDE_SUBSCRIPTION_PROVIDER,
            secret=NoSecret(),
            personal_owner_user_id=owner.user_id,
            claude_subscription_owner=owner,
        ),
    )
    calls = []

    def update_contact(name: str) -> str:
        """Update the named contact."""
        calls.append(name)
        return "Updated Sam at T3"

    def build(approval):
        toolset = FunctionToolset()
        toolset.add_function(update_contact, takes_ctx=False)
        return build_agent(
            AgentSpec(name="Contacts", instructions="Use the contact tool when requested."),
            model_spec,
            organization_id=owner.organization_id,
            user_id=owner.user_id,
            extra_toolsets=[toolset],
            request_approval=approval,
            gate_every_tool=True,
        )

    with patch("app.agents.claude_subscription.ClaudeSubscriptionRuntime", return_value=runtime):
        pending = AsyncMock(return_value=ApprovalPending())
        built = build(pending)
        parked = await built.agent.run("Update Sam", deps=built.deps)
        assert isinstance(parked.output, DeferredToolRequests)
        [call] = parked.output.approvals
        assert call.tool_name == "update_contact"
        assert calls == []
        assert runtime.infer.await_count == 1

        resumed_build = build(AsyncMock(return_value=ApprovalGranted(tool_args={"name": "Sam"})))
        resumed = await resumed_build.agent.run(
            deps=resumed_build.deps,
            message_history=parked.all_messages(),
            deferred_tool_results=DeferredToolResults(
                approvals={call.tool_call_id: ToolApproved(override_args={"name": "Sam"})}
            ),
        )

    assert resumed.output == "Contact updated."
    assert calls == ["Sam"]
    assert any(
        part["role"] == "tool" and "Updated Sam" in part["text"]
        for part in _prompt(runtime)["conversation"]
    )


async def test_structured_final_output_uses_the_actual_output_tool():
    class ContactAnswer(BaseModel):
        company: str

    model, runtime = _model()

    async def answer(owner, **kwargs):
        prompt = json.loads(kwargs["prompt"][kwargs["prompt"].index('{"instructions"') :])
        [output] = [tool for tool in prompt["available_tools"] if tool["kind"] == "output"]
        assert prompt["text_allowed"] is False
        return _reply(calls=[(output["name"], {"company": "T3"})])

    runtime.infer.side_effect = answer
    result = await Agent(model, output_type=ContactAnswer).run("Who employs Sam?")
    assert result.output == ContactAnswer(company="T3")


async def test_buffered_stream_delivers_completed_text_and_usage_once():
    model, runtime = _model(_reply("A complete answer."))
    async with Agent(model).run_stream("Hello") as result:
        chunks = [chunk async for chunk in result.stream_text(delta=True)]
    assert "".join(chunks) == "A complete answer."
    assert runtime.infer.await_count == 1
    assert result.usage.input_tokens == 15


async def test_full_history_preserves_call_ids_and_tool_results():
    model, runtime = _model(_reply("Done"))
    await Agent(model).run(
        "Continue",
        message_history=[
            ModelRequest(parts=[UserPromptPart("Find Sam")]),
            ModelResponse(
                parts=[
                    TextPart("Checking."),
                    ToolCallPart("lookup", {"name": "Sam"}, tool_call_id="existing-call"),
                ]
            ),
            ModelRequest(
                parts=[ToolReturnPart("lookup", {"company": "T3"}, tool_call_id="existing-call")]
            ),
        ],
    )
    conversation = _prompt(runtime)["conversation"]
    assert conversation[0] == {"role": "user", "text": "Find Sam"}
    call = next(part for part in conversation if part["role"] == "assistant_tool_call")
    result = next(part for part in conversation if part["role"] == "tool")
    assert call["call_id"] == result["call_id"] == "existing-call"
    assert "T3" in result["text"]
    assert conversation[-1]["text"] == "Continue"


async def test_tool_prepare_visibility_is_honored_each_step():
    model, runtime = _model(_reply("No tool available."))
    agent = Agent(model)

    async def hidden(ctx, definition):
        return None

    @agent.tool_plain(prepare=hidden)
    def private_contact() -> str:
        """Read a hidden contact."""
        raise AssertionError("A hidden tool must not execute")

    await agent.run("Look up a contact")
    assert _prompt(runtime)["available_tools"] == []


@pytest.mark.parametrize(
    "prompt",
    [
        ["Describe", ImageUrl("https://example.com/image.png")],
        [BinaryContent(data=b"sound", media_type="audio/wav")],
        [BinaryContent(data=b"document", media_type="application/pdf")],
        [BinaryContent(data=b"", media_type="image/png")],
    ],
)
async def test_unsupported_attachments_fail_before_inference(prompt):
    model, runtime = _model()
    with pytest.raises(UserError, match="text"):
        await Agent(model).run(prompt)
    runtime.infer.assert_not_awaited()


async def test_native_tools_fail_before_inference():
    model, runtime = _model()
    with pytest.raises(UserError, match="application tools, not provider-native tools"):
        await model.request(
            [ModelRequest(parts=[UserPromptPart("Search")])],
            None,
            ModelRequestParameters(native_tools=[WebSearchTool()]),
        )
    runtime.infer.assert_not_awaited()


@pytest.mark.parametrize(
    "decision",
    [
        {"text": None, "tool_calls": []},
        {"text": None, "tool_calls": [{"name": "hidden_tool", "arguments_json": "{}"}]},
        {"text": None, "tool_calls": [{"name": "lookup", "arguments_json": "[]"}]},
        {"text": None, "tool_calls": [{"name": "lookup", "arguments_json": "not JSON"}]},
        {"text": "hello", "tool_calls": [], "extra": "unexpected"},
    ],
)
async def test_invalid_native_decisions_never_create_executable_tools(decision):
    reply = _reply()
    reply.structured_output = decision
    model, _ = _model(reply)
    with pytest.raises(UnexpectedModelBehavior, match="invalid agent step"):
        await model.request(
            [ModelRequest(parts=[UserPromptPart("Hi")])],
            None,
            ModelRequestParameters(
                function_tools=[
                    ToolDefinition(
                        name="lookup", parameters_json_schema={"type": "object", "properties": {}}
                    )
                ],
            ),
        )


@pytest.mark.parametrize(
    "settings",
    [
        {"max_tokens": 1},
        {"max_tokens": 32001},
        {"stop_sequences": ["END"]},
        {"extra_headers": {"Authorization": "override"}},
        {"extra_body": {"model": "other"}},
    ],
)
async def test_unsupported_settings_fail_before_inference(settings):
    model, runtime = _model()
    with pytest.raises(UserError):
        await model.request(
            [ModelRequest(parts=[UserPromptPart("Hello")])], settings, ModelRequestParameters()
        )
    runtime.infer.assert_not_awaited()


async def test_required_named_tool_and_parallel_limit_are_enforced():
    model, runtime = _model(_reply(calls=[("lookup", {})]))
    await model.request(
        [ModelRequest(parts=[UserPromptPart("Hi")])],
        {"tool_choice": ["lookup"], "parallel_tool_calls": False, "max_tokens": 256},
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(name=name, parameters_json_schema={"type": "object"})
                for name in ["lookup", "hidden"]
            ],
        ),
    )
    payload = _prompt(runtime)
    assert [tool["name"] for tool in payload["available_tools"]] == ["lookup"]
    assert payload["maximum_tool_calls"] == 1
    assert runtime.infer.await_args.kwargs["max_output_tokens"] == 256


async def test_invalid_tool_arguments_are_repaired_by_the_existing_agent_loop():
    model, runtime = _model(
        _reply(calls=[("lookup", {"contact_id": "wrong"})]),
        _reply(calls=[("lookup", {"contact_id": 42})]),
        _reply("Found Sam"),
    )
    calls = []

    def lookup(contact_id: int) -> str:
        """Look up a contact by its numeric identifier."""
        calls.append(contact_id)
        return "Sam at T3"

    result = await Agent(model, tools=[lookup]).run("Find contact 42")
    assert result.output == "Found Sam"
    assert calls == [42]
    retry = next(part for part in _prompt(runtime, 1)["conversation"] if part["role"] == "tool")
    assert retry["name"] == "lookup"
    assert retry["outcome"] == "retried"
    assert "integer" in retry["text"]
    assert retry["call_id"]


async def test_global_model_request_prohibition_blocks_subscription_usage():
    model, runtime = _model()
    with override_allow_model_requests(False), pytest.raises(RuntimeError, match="not allowed"):
        await Agent(model).run("No live requests")
    runtime.infer.assert_not_awaited()


@pytest.mark.parametrize(
    "settings",
    [
        {"temperature": 0.1},
        {"top_p": 0.9},
        {"thinking": "ultracode"},
        {"thinking": 4096},
        {"thinking": {"budget_tokens": 4096}},
        {"cache": "1h"},
        {"timeout": 0},
        {"timeout": float("nan")},
    ],
)
async def test_sampling_and_unsupported_native_controls_are_explicitly_refused(settings):
    model, runtime = _model()
    with pytest.raises(UserError):
        await Agent(model, model_settings=settings).run("Hello")
    runtime.infer.assert_not_awaited()


async def test_user_timeout_cancels_the_private_inference_request():
    model, runtime = _model()
    cancelled = asyncio.Event()

    async def pending(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    runtime.infer.side_effect = pending
    with pytest.raises(TimeoutError):
        await Agent(model, model_settings={"timeout": 0.01}).run("Hello")
    assert cancelled.is_set()


@pytest.mark.parametrize(
    "thinking", [None, False, True, "minimal", "low", "medium", "high", "xhigh", "max"]
)
@pytest.mark.parametrize("source", ["capability", "model_settings"])
async def test_real_instrumented_agent_preserves_effective_thinking(thinking, source):
    model, runtime = _model(_reply("Ready"))
    capabilities = [Instrumentation()]
    if source == "capability" and thinking is not None:
        capabilities.append(Thinking(effort=thinking))
    model_settings = (
        {"thinking": thinking} if source == "model_settings" and thinking is not None else None
    )
    result = await Agent(model, capabilities=capabilities, model_settings=model_settings).run(
        "Hello"
    )
    assert result.output == "Ready"
    assert model.profile.get("supports_thinking") is True
    assert runtime.infer.await_args.kwargs["thinking"] == thinking


@pytest.mark.security
async def test_projected_thinking_survives_preparation_and_invalid_budget_is_refused():
    model, runtime = _model(_reply("Ready"))
    parameters = ModelRequestParameters(thinking="medium")
    prepared_settings, prepared = model.prepare_request(None, parameters)
    assert prepared.thinking == "medium"
    await model.request(
        [ModelRequest(parts=[UserPromptPart("Hello")])], prepared_settings, prepared
    )
    assert runtime.infer.await_args.kwargs["thinking"] == "medium"
    runtime.infer.reset_mock()
    parameters = ModelRequestParameters(thinking={"budget_tokens": 4096})
    with pytest.raises(UserError, match="token budgets"):
        model.prepare_request(None, parameters)
    runtime.infer.assert_not_awaited()


async def test_computer_tool_image_reaches_next_model_step_without_entering_stored_history():
    model, runtime = _model(
        _reply(calls=[("computer_screenshot", {})]), _reply("I see the desktop")
    )
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, "JPEG")
    screenshot = buffer.getvalue()

    def computer_screenshot() -> ToolReturn:
        """Capture the managed desktop."""
        return ToolReturn(
            return_value=["Desktop 1280x800", ephemeral_image(screenshot, "image/jpeg")]
        )

    result = await Agent(model, tools=[computer_screenshot]).run("Inspect the desktop")
    assert result.output == "I see the desktop"
    first = runtime.infer.await_args_list[0].kwargs
    second = runtime.infer.await_args_list[1].kwargs
    assert first["images"] == []
    [image] = second["images"]
    assert image.data == screenshot and image.media_type == "image/jpeg"
    assert "data=" not in repr(image)
    history = _prompt(runtime)["conversation"]
    call = next(part for part in history if part["role"] == "assistant_tool_call")
    returned = next(part for part in history if part["role"] == "tool")
    assert call["call_id"] == returned["call_id"]
    assert returned["name"] == "computer_screenshot" and "[image:1]" in returned["content"]
    assert "Desktop 1280x800" in returned["text"] or "Desktop 1280x800" in returned["content"]
    stored = json.dumps(dump_messages(result.all_messages()))
    assert "A screenshot the model was shown at the time" in stored
    assert '"kind": "binary"' not in stored


async def test_disabling_tools_keeps_their_definitions_out_of_the_native_prompt() -> None:
    model, runtime = _model(_reply("No tools requested"))
    result = await model.request(
        [ModelRequest(parts=[UserPromptPart("Answer without looking up contacts")])],
        {"tool_choice": "none"},
        ModelRequestParameters(function_tools=[ToolDefinition(name="lookup")]),
    )

    assert result.parts[0].content == "No tools requested"
    payload = _prompt(runtime)
    assert payload["available_tools"] == []
    assert payload["tool_required"] is False
    assert payload["text_allowed"] is True


async def test_a_required_function_call_cannot_be_satisfied_by_a_final_output_tool() -> None:
    model, runtime = _model(_reply(calls=[("lookup", {})]))
    await model.request(
        [ModelRequest(parts=[UserPromptPart("Look up Sam before answering")])],
        {"tool_choice": "required"},
        ModelRequestParameters(
            function_tools=[ToolDefinition(name="lookup")],
            output_tools=[ToolDefinition(name="final_answer", kind="output")],
            output_mode="tool",
        ),
    )

    payload = _prompt(runtime)
    assert [tool["name"] for tool in payload["available_tools"]] == ["lookup"]
    assert payload["tool_required"] is True
    assert payload["text_allowed"] is False


@pytest.mark.security
async def test_an_unsatisfiable_required_function_is_refused_before_native_inference() -> None:
    model, runtime = _model()
    with pytest.raises(UserError, match="no function tools are defined"):
        await model.request(
            [ModelRequest(parts=[UserPromptPart("A function is mandatory")])],
            {"tool_choice": "required"},
            ModelRequestParameters(
                output_tools=[ToolDefinition(name="final_answer", kind="output")],
                output_mode="tool",
            ),
        )
    runtime.infer.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    ("settings", "text", "call_count"),
    [
        ({"tool_choice": "required"}, "Forbidden prose", 1),
        ({"tool_choice": "required"}, None, 0),
        ({"parallel_tool_calls": False}, None, 2),
    ],
)
async def test_native_decisions_cannot_override_required_tools_or_the_parallel_limit(
    settings: ModelSettings, text: str | None, call_count: int
) -> None:
    model, runtime = _model(_reply(text, calls=[("lookup", {})] * call_count))
    with pytest.raises(UnexpectedModelBehavior, match="invalid agent step"):
        await model.request(
            [ModelRequest(parts=[UserPromptPart("Find Sam")])],
            settings,
            ModelRequestParameters(function_tools=[ToolDefinition(name="lookup")]),
        )
    runtime.infer.assert_awaited_once()


async def test_portable_history_keeps_summaries_and_text_without_provider_signatures() -> None:
    model, runtime = _model(_reply("Continue from the summary"))
    await model.request(
        [
            ModelResponse(
                parts=[
                    ThinkingPart("Visible reasoning text", signature="opaque-signature"),
                    ThinkingPart("", signature="opaque-empty-signature"),
                    CompactionPart("Sam works at T3", provider_details={"token": "opaque-token"}),
                ]
            ),
            ModelRequest(parts=[UserPromptPart("Continue")]),
        ],
        None,
        ModelRequestParameters(),
    )

    conversation = _prompt(runtime)["conversation"]
    assert conversation == [
        {"role": "assistant_reasoning", "text": "Visible reasoning text"},
        {"role": "conversation_summary", "text": "Sam works at T3"},
        {"role": "user", "text": "Continue"},
    ]
    assert "opaque" not in runtime.infer.await_args.kwargs["prompt"]


async def test_output_validation_feedback_reaches_the_next_native_step() -> None:
    model, runtime = _model(_reply("Incomplete"), _reply("Verified answer"))
    agent = Agent(model)

    @agent.output_validator
    def require_verification(output: str) -> str:
        if output != "Verified answer":
            raise ModelRetry("Include the verified result")
        return output

    result = await agent.run("Return the verified result")

    assert result.output == "Verified answer"
    assert runtime.infer.await_count == 2
    assert "Include the verified result" in runtime.infer.await_args.kwargs["prompt"]


@pytest.mark.security
async def test_an_output_tool_cannot_shadow_the_only_required_function() -> None:
    model, runtime = _model()
    with pytest.raises(UserError, match="No currently available tool"):
        await model.request(
            [ModelRequest(parts=[UserPromptPart("A function is mandatory")])],
            {"tool_choice": "required"},
            ModelRequestParameters(
                function_tools=[ToolDefinition(name="answer")],
                output_tools=[ToolDefinition(name="answer", kind="output")],
                output_mode="tool",
            ),
        )
    runtime.infer.assert_not_awaited()


@pytest.mark.parametrize("cause", ["validation_error", "no_output", "model_retry"])
async def test_saved_validation_feedback_is_preserved_in_native_history(cause: str) -> None:
    model, runtime = _model(_reply("A corrected answer"))
    await model.request(
        [
            ModelRequest(
                parts=[
                    RetryFeedbackPart(
                        "Keep this validation feedback",
                        retry=RetryInfo(cause, attempt=1, max_retries=3),
                    )
                ]
            )
        ],
        None,
        ModelRequestParameters(),
    )

    assert "Keep this validation feedback" in runtime.infer.await_args.kwargs["prompt"]


@pytest.mark.security
async def test_unsupported_native_history_is_refused_instead_of_silently_dropped() -> None:
    model, runtime = _model()
    with pytest.raises(UserError, match="conversation contains content"):
        await model.request(
            [
                ModelResponse(parts=[NativeToolCallPart("web_search", {"query": "Sam"})]),
                ModelRequest(parts=[UserPromptPart("Continue")]),
            ],
            None,
            ModelRequestParameters(),
        )
    runtime.infer.assert_not_awaited()
