"""Primary native conversations own their model request, receipt and process lifetime."""

import json
from typing import Literal
from unittest.mock import AsyncMock
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
        ) -> None:
            assert platform_tools and state_scope is not None
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
