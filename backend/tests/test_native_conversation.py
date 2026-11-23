"""Primary native conversations own their model request, receipt and process lifetime."""

import json
from typing import Literal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters

from app.agents import native_conversation as native
from app.agents.capabilities.coding_agent._harness import CodingReport, Said
from app.agents.native_conversation import NativeConversationModel
from app.schemas.local_target import LocalTarget
from tests.test_coding_agent_acp import _ctx, _local_workspace
from tests.test_runtime_tools import bridge

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("harness", ["codex", "claude_code", "external"])
async def test_primary_streaming_resumes_the_exact_native_receipt_and_sends_only_new_context(
    monkeypatch: pytest.MonkeyPatch,
    harness: Literal["codex", "claude_code", "external"],
) -> None:
    context = _ctx(_local_workspace(), [])
    from app.agents.audience import RunAudience

    context.deps.run_person = context.workspace.backend.owner_id
    context.deps.user_id = str(context.deps.run_person)
    context.deps.audience = RunAudience(user_id=context.deps.run_person)
    tools, _calls = await bridge()
    context.tool_manager = tools._ctx.tool_manager
    sessions: dict[str, str] = {}
    prompts: list[dict[str, object]] = []
    registration = "agy" if harness == "external" else None
    launched = "custom" if harness == "external" else harness

    class Pipe:
        def __init__(
            self,
            _workspace,
            acp_harness,
            *,
            resume_key: str,
            platform_tools: bool,
            custom_agent_id: str | None,
            state_scope: str | None,
            pi_key: object,
            runtime_model: str | None,
        ) -> None:
            assert runtime_model is None
            assert platform_tools and state_scope is not None and pi_key is None
            assert (acp_harness, custom_agent_id) == (launched, registration)
            self.scope = resume_key
            self.session_id = None
            self.auth_method = "gemini-api-key" if registration else None
            self.configuration_policy = "session"
            self.model_prefix = None
            self.protocol = "acp"

        async def open(self) -> None:
            self.session_id = sessions.get(self.scope)

        async def remember(self, identifier: str) -> None:
            sessions[self.scope] = identifier

        async def close(self) -> None:
            pass

    async def run(pipe, **options) -> CodingReport:
        assert options["harness"] == launched and options["auth_method"] == pipe.auth_method
        prompts.append(json.loads(options["task"]))
        identifier = pipe.session_id or f"native-{len(sessions)}"
        await options["remember"](identifier)
        await options["shown"]([Said("Hello"), Said(" world")])
        return CodingReport(
            harness=launched,
            access="edit",
            outcome="completed",
            answer="Hello world",
            session_id=identifier,
        )

    monkeypatch.setattr(native, "DevicePipe", Pipe)
    monkeypatch.setattr(native, "run_task", run)
    model = NativeConversationModel(
        harness=harness, epoch=str(uuid4()), access="edit", registration_id=registration
    )
    history = [ModelRequest.user_text_prompt("first", instructions="Instruction one")]
    async with model.request_stream(history, None, ModelRequestParameters(), context) as stream:
        events = [event async for event in stream]
        first = stream.get()
    assert events and first.parts == [TextPart("Hello world")]
    assert first.state == "complete" and first.usage.unmeasured_requests == 1
    history.extend(
        [first, ModelRequest.user_text_prompt("second", instructions="Updated instructions")]
    )
    async with model.request_stream(history, None, ModelRequestParameters(), context) as stream:
        _ = [event async for event in stream]
        second = stream.get()
    assert (
        second.provider_details["agenticos_native_conversation"]["session_id"]
        == first.provider_details["agenticos_native_conversation"]["session_id"]
    )
    assert prompts[1]["agent_instructions"] == "Updated instructions"
    assert prompts[1]["conversation_context"] == [
        {"role": "request", "parts": [{"user": "second"}]}
    ]
    tampered = [ModelRequest.user_text_prompt("edited past"), *history[1:]]
    with pytest.raises(native.AcpError, match="history changed"):
        async with model.request_stream(
            tampered, None, ModelRequestParameters(), context
        ) as stream:
            _ = [event async for event in stream]
    assert len(prompts) == 2
    sessions.clear()
    with pytest.raises(native.AcpError, match="no matching settled"):
        async with model.request_stream(history, None, ModelRequestParameters(), context) as stream:
            _ = [event async for event in stream]
    assert len(prompts) == 2


@pytest.mark.parametrize("change", ["shared", "impersonated", "other_user", "no_person"])
async def test_primary_runtime_cannot_borrow_another_person_or_a_shared_conversation(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from dataclasses import replace

    context = _ctx(_local_workspace(), [])
    from app.agents.audience import RunAudience

    context.deps.run_person = context.workspace.backend.owner_id
    context.deps.user_id = str(context.deps.run_person)
    context.deps.audience = RunAudience(user_id=context.deps.run_person)
    if change == "shared":
        context.deps.audience = replace(context.deps.audience, shared_transcript=True)
    elif change == "impersonated":
        context.deps.impersonated = True
    elif change == "other_user":
        context.deps.user_id = str(uuid4())
    else:
        context.deps.run_person = None
    opened = AsyncMock()
    monkeypatch.setattr(native, "run_task", opened)
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="read_only")
    with pytest.raises(native.AcpError, match="initiating member"):
        async with model.request_stream(
            [ModelRequest.user_text_prompt("hello")], None, ModelRequestParameters(), context
        ) as stream:
            _ = [event async for event in stream]
    opened.assert_not_called()


def test_native_target_requires_a_full_access_folder_and_an_explicit_epoch() -> None:
    epoch = str(uuid4())
    valid = {
        "folder": "/work",
        "mode": "full_access",
        "conversation_runtime": {"harness": "codex", "session_epoch": epoch},
    }
    assert str(LocalTarget.model_validate(valid).conversation_runtime.session_epoch) == epoch
    for changes in [{"mode": "read_only"}, {"model_service": "local"}, {"folder": None}]:
        with pytest.raises(ValidationError):
            LocalTarget.model_validate(valid | changes)
    with pytest.raises(ValidationError):
        LocalTarget.model_validate(valid | {"conversation_runtime": {"harness": "codex"}})


async def test_read_only_forwarding_uses_the_platform_classifier_and_denies_unknown_tools() -> None:
    from app.agents.isolation import ToolClass
    from app.agents.runtime_tools import RuntimeTools

    runtime, calls = await bridge()
    blocked = RuntimeTools(runtime._ctx, readonly_tools={})
    assert await blocked.dispatch("_agenticos/tools/list", {}) == {"tools": []}
    with pytest.raises(ValueError, match="unavailable"):
        await blocked.dispatch(
            "_agenticos/tools/call", {"name": "increment", "arguments": {"value": 1}}
        )
    allowed = RuntimeTools(
        runtime._ctx, readonly_tools={"increment": ToolClass(tool_id="owned:read", read_only=True)}
    )
    assert (await allowed.dispatch("_agenticos/tools/list", {}))["tools"]
    assert not calls


async def test_factory_binds_native_primary_context_without_a_cloud_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.audience import RunAudience
    from app.agents.factory import build_agent
    from app.agents.model_resolver import ResolvedCredential
    from app.agents.native_model_spec import NativeModelSpec, current_native_context
    from app.agents.spec import AgentSpec
    from app.core.secret_kinds import NoSecret
    from app.schemas.local_target import NativeConversationTarget

    person, profile = uuid4(), uuid4()
    seen = []

    async def run(self, ctx, messages, parameters, text):
        assert current_native_context() is ctx
        seen.append(ctx.deps)
        return ModelResponse(
            [TextPart("Native primary answer")],
            model_name="native-codex",
            provider_name="native-codex",
        )

    monkeypatch.setattr(NativeConversationModel, "_run", run)
    model = NativeModelSpec(
        profile_id=profile,
        label="Codex native",
        provider="native-codex",
        model="native-codex",
        params={},
        credential=ResolvedCredential(provider="native-codex", secret=NoSecret()),
        fallbacks=[],
        readonly_tools={},
        target=NativeConversationTarget(harness="codex", session_epoch=uuid4()),
    )
    built = build_agent(
        AgentSpec(name="native", model_profile_id=profile),
        model,
        organization_id=uuid4(),
        conversation_id=uuid4(),
        user_id=str(person),
        run_person=person,
        audience=RunAudience(user_id=person),
    )
    result = await built.agent.run("Hello", deps=built.deps)
    assert result.output == "Native primary answer"
    assert seen == [built.deps] and built.deps.audience.user_id == person
    assert current_native_context() is None


async def test_explicit_stream_stop_waits_for_owned_cleanup_and_never_creates_a_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anyio

    context = _ctx(_local_workspace(), [])
    entered, closed = anyio.Event(), anyio.Event()

    async def pending(self, ctx, messages, parameters, text):
        entered.set()
        try:
            await anyio.sleep_forever()
        finally:
            closed.set()

    monkeypatch.setattr(NativeConversationModel, "_run", pending)
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="read_only")
    async with model.request_stream(
        [ModelRequest.user_text_prompt("work")], None, ModelRequestParameters(), context
    ) as stream:
        await entered.wait()
        await stream.cancel()
        assert closed.is_set()
        _ = [event async for event in stream]
        response = stream.get()
        assert response.state == "interrupted" and response.provider_details is None


def test_inactive_native_selection_preserves_existing_local_consent_fingerprints() -> None:
    import hashlib

    target = LocalTarget(folder="/work", mode="workspace_write")
    legacy = target.model_dump(mode="json", exclude={"conversation_runtime"})
    assert (
        target.fingerprint()
        == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    )


def test_operator_eligibility_is_separate_from_a_native_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.services.model_profile import native_runtime_availability

    monkeypatch.setattr(settings, "CODEX_NATIVE_CONVERSATION_ENABLED", False)
    assert not native_runtime_availability().codex
    monkeypatch.setattr(settings, "CODEX_NATIVE_CONVERSATION_ENABLED", True)
    assert native_runtime_availability().codex
    monkeypatch.setattr(settings, "EXTERNAL_NATIVE_CONVERSATION_ENABLED", False)
    assert not native_runtime_availability().external
    monkeypatch.setattr(settings, "EXTERNAL_NATIVE_CONVERSATION_ENABLED", True)
    assert native_runtime_availability().external


async def test_an_external_runtime_refuses_a_registration_that_does_not_speak_acp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pi registrations take delegated tasks over RPC; a primary turn needs ACP."""
    context = _ctx(_local_workspace(), [])
    from app.agents.audience import RunAudience

    context.deps.run_person = context.workspace.backend.owner_id
    context.deps.user_id = str(context.deps.run_person)
    context.deps.audience = RunAudience(user_id=context.deps.run_person)
    tools, _calls = await bridge()
    context.tool_manager = tools._ctx.tool_manager
    closed: list[bool] = []

    class Pipe:
        def __init__(self, *_args, **_kwargs) -> None:
            self.session_id = None
            self.protocol = "pi_rpc"

        async def open(self) -> None:
            pass

        async def close(self) -> None:
            closed.append(True)

    run = AsyncMock()
    monkeypatch.setattr(native, "DevicePipe", Pipe)
    monkeypatch.setattr(native, "run_task", run)
    model = NativeConversationModel(
        harness="external", epoch=str(uuid4()), access="edit", registration_id="pi-deepseek"
    )
    with pytest.raises(native.AcpError, match="does not speak ACP"):
        async with model.request_stream(
            [ModelRequest.user_text_prompt("hello")], None, ModelRequestParameters(), context
        ) as stream:
            _ = [event async for event in stream]
    run.assert_not_awaited()
    assert closed == [True]


def test_only_an_external_runtime_names_a_registration_and_it_never_claims_read_only() -> None:
    from app.schemas.local_target import NativeConversationTarget

    epoch = uuid4()
    chosen = NativeConversationTarget(
        harness="external", session_epoch=epoch, access="edit", registration_id="agy"
    )
    assert chosen.registration_id == "agy"
    with pytest.raises(ValidationError, match="requires its Desktop registration"):
        NativeConversationTarget(harness="external", session_epoch=epoch, access="edit")
    with pytest.raises(ValidationError, match="choose edit"):
        NativeConversationTarget(harness="external", session_epoch=epoch, registration_id="agy")
    with pytest.raises(ValidationError, match="Only an external runtime"):
        NativeConversationTarget(harness="codex", session_epoch=epoch, secret_id=uuid4())
    with pytest.raises(ValidationError, match="Only an external runtime"):
        NativeConversationTarget(harness="codex", session_epoch=epoch, registration_id="agy")
    with pytest.raises(ValidationError):
        NativeConversationTarget(
            harness="external", session_epoch=epoch, access="edit", registration_id="../agy"
        )
    with pytest.raises(native.AcpError, match="Desktop registration"):
        NativeConversationModel(harness="external", epoch=str(epoch), access="edit")
    with pytest.raises(native.AcpError, match="Desktop registration"):
        NativeConversationModel(
            harness="codex", epoch=str(epoch), access="edit", registration_id="agy"
        )


async def test_a_vault_gemini_key_reaches_only_the_launch_and_never_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key crosses to Desktop once; split chunks cannot leak it into the chat."""
    from app.agents.audience import RunAudience
    from app.agents.pi_keys import NativeRuntimeKey

    context = _ctx(_local_workspace(), [])
    context.deps.run_person = context.workspace.backend.owner_id
    context.deps.user_id = str(context.deps.run_person)
    context.deps.audience = RunAudience(user_id=context.deps.run_person)
    tools, _calls = await bridge()
    context.tool_manager = tools._ctx.tool_manager
    secret = uuid4()
    key = NativeRuntimeKey(provider="gemini", api_key="AIza-secret-value", revision="a" * 64)
    requested: list[tuple[str | None, object]] = []

    async def selected(_ctx, provider, secret_id):
        requested.append((provider, secret_id))
        return key if secret_id is not None else None

    launched: list[object] = []

    class Pipe:
        def __init__(self, *_args, pi_key: object, **_kwargs) -> None:
            launched.append(pi_key)
            self.session_id = None
            self.auth_method = "gemini-api-key"
            self.configuration_policy = "session"
            self.model_prefix = None
            self.protocol = "acp"

        async def open(self) -> None:
            pass

        async def remember(self, identifier: str) -> None:
            pass

        async def close(self) -> None:
            pass

    async def run(pipe, **options) -> CodingReport:
        with pytest.raises(ValueError, match="Credential"):
            await options["platform_tools"].dispatch(
                "_agenticos/tools/call",
                {"name": "increment", "arguments": {"value": key.api_key.get_secret_value()}},
            )
        assert _calls == []
        await options["shown"]([Said("Key AIza-sec"), Said("ret-value is set")])
        return CodingReport(
            harness="custom", access="edit", outcome="completed", answer="", session_id="s1"
        )

    monkeypatch.setattr(native, "selected_key", selected)
    monkeypatch.setattr(native, "DevicePipe", Pipe)
    monkeypatch.setattr(native, "run_task", run)
    model = NativeConversationModel(
        harness="external",
        epoch=str(uuid4()),
        access="edit",
        registration_id="agy-key",
        secret_id=secret,
    )
    async with model.request_stream(
        [ModelRequest.user_text_prompt("hello")], None, ModelRequestParameters(), context
    ) as stream:
        events = [event async for event in stream]
        response = stream.get()
    assert requested == [("gemini", secret)] and launched == [key]
    assert response.parts == [TextPart("Key [redacted] is set")]
    assert "secret-value" not in repr(events)
    with pytest.raises(native.AcpError, match="vault key"):
        NativeConversationModel(
            harness="codex", epoch=str(uuid4()), access="edit", secret_id=secret
        )


async def test_a_keyed_runtime_refuses_a_question_carrying_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.audience import RunAudience
    from app.agents.pi_keys import NativeRuntimeKey

    context = _ctx(_local_workspace(), [])
    context.deps.run_person = context.workspace.backend.owner_id
    context.deps.user_id = str(context.deps.run_person)
    context.deps.audience = RunAudience(user_id=context.deps.run_person)
    asked = AsyncMock()
    context.deps.runtime_questions = asked
    tools, _calls = await bridge()
    context.tool_manager = tools._ctx.tool_manager
    key = NativeRuntimeKey(provider="gemini", api_key="AIza-secret-value", revision="b" * 64)

    async def selected(_ctx, _provider, _secret_id):
        return key

    class Pipe:
        def __init__(self, *_args, **_kwargs) -> None:
            self.session_id = None
            self.auth_method = "gemini-api-key"
            self.configuration_policy = "session"
            self.model_prefix = None
            self.protocol = "acp"

        async def open(self) -> None:
            pass

        async def remember(self, identifier: str) -> None:
            pass

        async def close(self) -> None:
            pass

    seen: list[str] = []

    async def run(pipe, **options) -> CodingReport:
        request = MagicMock()
        request.model_dump_json.return_value = '{"title": "AIza-secret-value"}'
        try:
            await options["runtime_questions"](request)
        except native.AcpError as refused:
            seen.append(refused.message)
        clean = MagicMock()
        clean.model_dump_json.return_value = '{"title": "Continue?"}'
        await options["runtime_questions"](clean)
        await options["shown"]([Said("done")])
        return CodingReport(
            harness="custom", access="edit", outcome="completed", answer="done", session_id="s"
        )

    monkeypatch.setattr(native, "selected_key", selected)
    monkeypatch.setattr(native, "DevicePipe", Pipe)
    monkeypatch.setattr(native, "run_task", run)
    model = NativeConversationModel(
        harness="external",
        epoch=str(uuid4()),
        access="edit",
        registration_id="k",
        secret_id=uuid4(),
    )
    async with model.request_stream(
        [ModelRequest.user_text_prompt("hello")], None, ModelRequestParameters(), context
    ) as stream:
        _ = [event async for event in stream]
    assert seen and "credential material" in seen[0]
    asked.assert_awaited_once()
    context.deps.runtime_questions = None
    async with model.request_stream(
        [ModelRequest.user_text_prompt("again")], None, ModelRequestParameters(), context
    ) as stream:
        _ = [event async for event in stream]


async def _private_context():
    from app.agents.audience import RunAudience

    context = _ctx(_local_workspace(), [])
    context.deps.run_person = context.workspace.backend.owner_id
    context.deps.user_id = str(context.deps.run_person)
    context.deps.audience = RunAudience(user_id=context.deps.run_person)
    tools, _calls = await bridge()
    context.tool_manager = tools._ctx.tool_manager
    return context


def _fake_pipe(closed: list[str] | None = None, *, close_error: BaseException | None = None):
    class Pipe:
        def __init__(self, *_args, **_kwargs) -> None:
            self.session_id = None
            self.auth_method = None
            self.configuration_policy = "session"
            self.model_prefix = None
            self.protocol = "acp"

        async def open(self) -> None:
            pass

        async def remember(self, identifier: str) -> None:
            pass

        async def close(self) -> None:
            if closed is not None:
                closed.append("closed")
            if close_error is not None:
                raise close_error

    return Pipe


async def _stream_all(model, messages, context, parameters=None):
    async with model.request_stream(
        messages, None, parameters or ModelRequestParameters(), context
    ) as stream:
        _ = [event async for event in stream]
        return stream.get()


def test_history_keeps_tools_and_corrections_and_drops_instructions_and_thinking() -> None:
    from pydantic_ai.messages import (
        RetryFeedbackPart,
        RetryInfo,
        SystemPromptPart,
        ThinkingPart,
        ToolCallPart,
        ToolReturnPart,
    )

    rows = native.history_rows(
        [
            ModelRequest([SystemPromptPart("system"), native.UserPromptPart(["a", "b"])]),
            ModelResponse(
                [ThinkingPart("hidden"), ToolCallPart("lookup", {"q": 1}, tool_call_id="c1")]
            ),
            ModelRequest(
                [
                    ToolReturnPart("lookup", "found", tool_call_id="c1"),
                    RetryFeedbackPart("try again", retry=RetryInfo("model_retry")),
                ]
            ),
        ]
    )
    assert rows[0] == {"role": "request", "parts": [{"user": "a\nb"}]}
    assert rows[1]["parts"] == [{"tool": "lookup", "arguments": '{"q":1}', "id": "c1"}]
    assert rows[2]["parts"][0] == {"tool_result": "found", "id": "c1"}
    assert "correction" in rows[2]["parts"][1]


def test_history_refuses_files_and_parts_it_cannot_represent() -> None:
    from pydantic_ai.messages import BinaryContent, FilePart

    image = BinaryContent(data=b"\x89PNG", media_type="image/png")
    with pytest.raises(native.AcpError, match="text only"):
        native.history_rows([ModelRequest([native.UserPromptPart(["look", image])])])
    with pytest.raises(native.AcpError, match="cannot represent"):
        native.history_rows([ModelResponse([FilePart(image)])])


async def test_requests_without_their_owned_run_context_are_refused() -> None:
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    with pytest.raises(native.AcpError, match="owned run context"):
        await model.request([], None, ModelRequestParameters())
    with pytest.raises(native.AcpError, match="owned run context"):
        async with model.request_stream([], None, ModelRequestParameters()):
            pass


async def test_the_non_streaming_signature_uses_the_bound_context_and_discards_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.native_model_spec import _BOUND

    context = await _private_context()
    seen: list[object] = []

    async def run(self, ctx, messages, parameters, text):
        seen.append(ctx)
        await text("ignored delta")
        return ModelResponse([TextPart("whole")])

    monkeypatch.setattr(NativeConversationModel, "_run", run)
    token = _BOUND.set(context)
    try:
        model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
        response = await model.request([], None, ModelRequestParameters())
    finally:
        _BOUND.reset(token)
    assert seen == [context] and response.parts == [TextPart("whole")]


async def test_several_concurrent_stream_failures_are_not_reduced_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Group:
        cancel_scope = MagicMock()

        async def __aenter__(self):
            return self

        async def start(self, _function) -> None:
            return None

        async def __aexit__(self, *_exc) -> None:
            raise BaseExceptionGroup("both", [ValueError("one"), KeyError("two")])

    monkeypatch.setattr(native.anyio, "create_task_group", Group)
    context = await _private_context()
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    with pytest.raises(BaseExceptionGroup) as raised:
        async with model.request_stream([], None, ModelRequestParameters(), context):
            pass
    assert len(raised.value.exceptions) == 2


async def test_structured_output_is_refused_before_any_native_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _private_context()
    launched = MagicMock()
    monkeypatch.setattr(native, "DevicePipe", launched)
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    with pytest.raises(native.AcpError, match="text answers"):
        await _stream_all(
            model,
            [ModelRequest.user_text_prompt("hi")],
            context,
            ModelRequestParameters(output_mode="native"),
        )
    launched.assert_not_called()


async def test_an_incompatible_receipt_requires_an_explicit_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _private_context()
    monkeypatch.setattr(native, "DevicePipe", _fake_pipe())
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    broken = ModelResponse([TextPart("old")])
    broken.provider_details = {"agenticos_native_conversation": {"scope": "nope"}}
    with pytest.raises(native.AcpError, match="incompatible"):
        await _stream_all(
            model,
            [ModelRequest.user_text_prompt("a"), broken, ModelRequest.user_text_prompt("b")],
            context,
        )


async def test_another_scopes_receipt_and_plain_answers_start_a_fresh_native_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _private_context()
    monkeypatch.setattr(native, "DevicePipe", _fake_pipe())
    prompts: list[dict[str, object]] = []

    async def run(pipe, **options) -> CodingReport:
        prompts.append(json.loads(options["task"]))
        return CodingReport(
            harness="codex", access="edit", outcome="completed", answer="fresh", session_id="n1"
        )

    monkeypatch.setattr(native, "run_task", run)
    other = ModelResponse([TextPart("from another runtime")])
    other.provider_details = {
        "agenticos_native_conversation": {"scope": "a" * 64, "digest": "b" * 64, "session_id": "x"}
    }
    plain = ModelResponse([TextPart("from the model profile")])
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    response = await _stream_all(
        model,
        [ModelRequest.user_text_prompt("a"), other, ModelRequest.user_text_prompt("b"), plain],
        context,
    )
    assert response.parts == [TextPart("fresh")]
    assert len(prompts[0]["conversation_context"]) == 4


async def test_oversized_context_and_answers_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agents.capabilities.coding_agent._harness import CodingStep, StepStarted

    context = await _private_context()
    closed: list[str] = []
    monkeypatch.setattr(native, "DevicePipe", _fake_pipe(closed))
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    with pytest.raises(native.AcpError, match="2 MiB"):
        await _stream_all(model, [ModelRequest.user_text_prompt("x" * (3 << 20))], context)

    async def chatty(pipe, **options) -> CodingReport:
        await options["shown"](
            [StepStarted(key="s", step=CodingStep(kind="read", title="Reading"))]
        )
        await options["shown"]([Said("y" * 128001)])
        raise AssertionError("unreachable")

    monkeypatch.setattr(native, "run_task", chatty)
    with pytest.raises(native.AcpError, match="retention limit"):
        await _stream_all(model, [ModelRequest.user_text_prompt("hi")], context)
    assert closed == ["closed"]


@pytest.mark.parametrize(
    ("report", "message"),
    [
        ({"outcome": "failed", "answer": "", "session_id": "s"}, "did not settle"),
        ({"outcome": "completed", "answer": "", "session_id": None}, "did not settle"),
        ({"outcome": "completed", "answer": "", "session_id": "s"}, "without a text answer"),
    ],
)
async def test_an_unsettled_or_empty_turn_records_no_receipt(
    monkeypatch: pytest.MonkeyPatch, report: dict[str, object], message: str
) -> None:
    context = await _private_context()
    monkeypatch.setattr(native, "DevicePipe", _fake_pipe())

    async def run(pipe, **options) -> CodingReport:
        return CodingReport(harness="codex", access="edit", **report)

    monkeypatch.setattr(native, "run_task", run)
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    with pytest.raises(native.AcpError, match=message):
        await _stream_all(model, [ModelRequest.user_text_prompt("hi")], context)


async def test_a_failed_close_after_settlement_is_still_counted_and_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _private_context()
    monkeypatch.setattr(native, "DevicePipe", _fake_pipe(close_error=OSError("pipe broke")))
    recorded = MagicMock()
    monkeypatch.setattr(native, "record_ambient_usage", recorded)

    async def run(pipe, **options) -> CodingReport:
        return CodingReport(
            harness="codex", access="edit", outcome="completed", answer="ok", session_id="s"
        )

    monkeypatch.setattr(native, "run_task", run)
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    with pytest.raises(OSError, match="pipe broke"):
        await _stream_all(model, [ModelRequest.user_text_prompt("hi")], context)
    recorded.assert_called_once()

    async def failing(pipe, **options) -> CodingReport:
        raise native.AcpError("runtime exited")

    monkeypatch.setattr(native, "run_task", failing)
    with pytest.raises(OSError, match="pipe broke"):
        await _stream_all(model, [ModelRequest.user_text_prompt("hi")], context)
    assert recorded.call_count == 2


async def test_a_stream_without_a_settled_response_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _private_context()

    async def nothing(self, ctx, messages, parameters, text):
        return None

    monkeypatch.setattr(NativeConversationModel, "_run", nothing)
    model = NativeConversationModel(harness="codex", epoch=str(uuid4()), access="edit")
    with pytest.raises(native.AcpError, match="without settlement"):
        await _stream_all(model, [ModelRequest.user_text_prompt("hi")], context)
    import anyio

    idle = native.NativeStream(
        model_request_parameters=ModelRequestParameters(),
        native=model,
        receiver=anyio.create_memory_object_stream[str](1)[1],
    )
    await idle.close_stream()


def test_a_selected_native_runtime_changes_the_local_consent_fingerprint() -> None:
    from app.schemas.local_target import NativeConversationTarget

    plain = LocalTarget(folder="/work", mode="full_access")
    native_target = plain.model_copy(
        update={
            "conversation_runtime": NativeConversationTarget(harness="codex", session_epoch=uuid4())
        }
    )
    assert plain.fingerprint() != native_target.fingerprint()
