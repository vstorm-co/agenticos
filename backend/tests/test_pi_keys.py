"""Selected-key Pi lanes keep billing, native ownership and vault access explicit."""

import hashlib
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.agents.audience import RunAudience
from app.agents.capabilities.coding_agent._acp import AcpError, DevicePipe
from app.agents.capabilities.external_acp import ExternalAcpConfig
from app.agents.capabilities.external_acp._catalog import AcpCatalog, AcpChoice
from app.agents.capabilities.external_acp._keys import catalog_json, selected_key
from app.agents.capabilities.external_acp._pi import inspect_pi, run_pi
from app.agents.pi_keys import NativeRuntimeKey
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.secret_kinds import ApiKeySecret
from app.repositories import member_repo, organization_secret_repo
from app.services.organization_secret import OrganizationSecretService
from tests.test_coding_agent_acp import FakeDevice, _ctx, _local_workspace
from tests.test_pi_rpc import MODEL, Pi, ignore
from tests.test_secrets import _ctx as secret_context
from tests.test_secrets import _db, _row

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def key(provider: str = "deepseek") -> NativeRuntimeKey:
    return NativeRuntimeKey.model_validate(
        {"provider": provider, "api_key": "selected-private-key", "revision": "a" * 64}
    )


def test_keys_are_masked_except_for_the_explicit_native_payload() -> None:
    selected = key()
    assert "selected-private-key" not in repr(selected)
    assert "selected-private-key" not in selected.model_dump_json()
    assert selected.native_payload("deepseek/native-model") == {
        "provider": "deepseek",
        "api_key": "selected-private-key",
        "model_id": "deepseek/native-model",
    }
    for value in ["tinykey", "private\nkey", "private\rkey", "private key"]:
        with pytest.raises(ValidationError) as invalid:
            NativeRuntimeKey(provider="deepseek", api_key=SecretStr(value), revision="a" * 64)
        assert value not in str(invalid.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"model_id": None},
        {"model_id": "other/model"},
        {"model_id": "deepseek/model", "auth_method": "oauth-personal"},
    ],
)
def test_key_configuration_refuses_ambiguous_model_or_oauth(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExternalAcpConfig.model_validate(
            {"agent_id": "pi-key", "api_provider": "deepseek", **changes}
        )


async def test_vault_visibility_and_live_membership_are_checked_before_native_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = secret_context()
    row = _row(context, ApiKeySecret(api_key=SecretStr("selected-private-key")))
    row.purpose = "deepseek"
    member = AsyncMock(role="member")
    monkeypatch.setattr(member_repo, "get", AsyncMock(return_value=member))
    monkeypatch.setattr(organization_secret_repo, "get", AsyncMock(return_value=row))
    access = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.organization_secret.resolve_access", access)
    service = OrganizationSecretService(_db())
    selected = await service.native_runtime_key(
        organization_id=context.organization_id,
        user_id=context.user_id,
        secret_id=row.id,
        provider="deepseek",
    )
    assert selected.api_key.get_secret_value() == "selected-private-key"
    assert selected.revision == hashlib.sha256(row.sealed_secret.encode()).hexdigest()
    assert access.call_args.args[1].user_id == context.user_id
    row.purpose = "openrouter"
    with pytest.raises(BadRequestError):
        await service.native_runtime_key(
            organization_id=context.organization_id,
            user_id=context.user_id,
            secret_id=row.id,
            provider="deepseek",
        )
    row.purpose = "deepseek"
    access.return_value = False
    with pytest.raises(NotFoundError):
        await service.native_runtime_key(
            organization_id=context.organization_id,
            user_id=context.user_id,
            secret_id=row.id,
            provider="deepseek",
        )
    monkeypatch.setattr(member_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await service.native_runtime_key(
            organization_id=context.organization_id,
            user_id=context.user_id,
            secret_id=row.id,
            provider="deepseek",
        )


@pytest.mark.parametrize(
    "change",
    [
        "impersonated",
        "missing_person",
        "missing_org",
        "audience",
        "room",
        "shared_transcript",
        "other_computer",
        "user_id",
        "no_workspace",
    ],
)
async def test_native_export_requires_the_initiating_members_own_private_computer(
    change: str,
) -> None:
    context = _ctx(_local_workspace(), [])
    person = context.workspace.backend.owner_id
    context.deps.run_person = person
    context.deps.user_id = str(person)
    context.deps.audience = RunAudience(user_id=person)
    if change == "impersonated":
        context.deps.impersonated = True
    elif change == "missing_person":
        context.deps.run_person = None
    elif change == "missing_org":
        context.deps.organization_id = None
    elif change == "audience":
        context.deps.audience = None
    elif change == "room":
        context.deps.audience = RunAudience(user_id=person, room_key="room:shared")
    elif change == "shared_transcript":
        context.deps.audience = RunAudience(user_id=person, shared_transcript=True)
    elif change == "other_computer":
        context.deps.run_person = uuid4()
    elif change == "user_id":
        context.deps.user_id = str(uuid4())
    elif change == "no_workspace":
        context = _ctx(None, [])
    with pytest.raises(AuthorizationError):
        await selected_key(context, "deepseek", uuid4())
    assert await selected_key(context, None, None) is None


async def test_native_selection_loads_the_current_key_and_requires_a_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _ctx(_local_workspace(), [])
    person = context.workspace.backend.owner_id
    context.deps.run_person = person
    context.deps.user_id = str(person)
    context.deps.audience = RunAudience(user_id=person)
    with pytest.raises(BadRequestError):
        await selected_key(context, "deepseek", None)

    @asynccontextmanager
    async def database():
        yield _db()

    monkeypatch.setattr("app.agents.capabilities.external_acp._keys.get_db_context", database)
    load = AsyncMock(return_value=key())
    monkeypatch.setattr(OrganizationSecretService, "native_runtime_key", load)
    secret_id = uuid4()
    assert await selected_key(context, "deepseek", secret_id) == key()
    assert load.call_args.kwargs["user_id"] == person
    assert load.call_args.kwargs["secret_id"] == secret_id


async def test_a_native_provider_acknowledgement_is_required_before_any_prompt() -> None:
    for opened in [
        {"id": "one", "protocol": "pi_rpc"},
        {"id": "one", "protocol": "acp", "pi_provider": "deepseek"},
        {"id": "one", "protocol": "pi_rpc", "pi_provider": "openrouter"},
    ]:
        device = FakeDevice([], opened=opened)
        pipe = DevicePipe(
            device,
            "custom",
            custom_agent_id="pi-key",
            pi_key=key(),
            pi_model="deepseek/native-model",
        )
        with pytest.raises(AcpError, match="exact vault-key provider"):
            await pipe.open()
        assert device.calls[-1][0] == "agent.close"
        assert device.calls[0][1]["pi_key"] == key().native_payload("deepseek/native-model")
    device = FakeDevice([], opened={"id": "one", "protocol": "pi_rpc", "pi_provider": "deepseek"})
    await DevicePipe(
        device, "custom", custom_agent_id="pi-key", pi_key=key(), pi_model="deepseek/native-model"
    ).open()


async def test_a_gemini_vault_key_needs_desktops_acknowledgement_and_no_pi_payload() -> None:
    gemini = NativeRuntimeKey(provider="gemini", api_key="AIza-private-key", revision="c" * 64)
    assert gemini.pi_provider is None and key().pi_provider == "deepseek"
    refused = FakeDevice([], opened={"id": "one", "protocol": "acp"})
    with pytest.raises(AcpError, match="exact vault-key provider"):
        await DevicePipe(refused, "custom", custom_agent_id="agy-key", pi_key=gemini).open()
    assert refused.calls[0][1]["gemini_key"] == "AIza-private-key"
    assert "pi_key" not in refused.calls[0][1] and refused.calls[-1][0] == "agent.close"
    device = FakeDevice([], opened={"id": "one", "protocol": "acp", "gemini_key": True})
    await DevicePipe(device, "custom", custom_agent_id="agy-key", pi_key=gemini).open()


def test_a_gemini_key_lane_needs_no_model_but_keeps_the_program_login() -> None:
    config = ExternalAcpConfig.model_validate({"agent_id": "agy-key", "api_provider": "gemini"})
    assert config.api_provider == "gemini" and config.model_id is None
    with pytest.raises(ValidationError, match="program setting"):
        ExternalAcpConfig.model_validate(
            {"agent_id": "agy-key", "api_provider": "gemini", "auth_method": "oauth-personal"}
        )


async def test_a_gemini_export_accepts_google_or_custom_keys_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = secret_context()
    row = _row(context, ApiKeySecret(api_key=SecretStr("AIza-private-key")))
    monkeypatch.setattr(member_repo, "get", AsyncMock(return_value=AsyncMock(role="member")))
    monkeypatch.setattr(organization_secret_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(
        "app.services.organization_secret.resolve_access", AsyncMock(return_value=True)
    )
    service = OrganizationSecretService(_db())
    for purpose in ("google", "custom"):
        row.purpose = purpose
        exported = await service.native_runtime_key(
            organization_id=context.organization_id,
            user_id=context.user_id,
            secret_id=row.id,
            provider="gemini",
        )
        assert exported.provider == "gemini"
    row.purpose = "gemini"
    with pytest.raises(BadRequestError):
        await service.native_runtime_key(
            organization_id=context.organization_id,
            user_id=context.user_id,
            secret_id=row.id,
            provider="gemini",
        )


async def test_selected_model_must_be_acknowledged_by_pi_before_inference() -> None:
    class SelectedPi(Pi):
        async def send(self, message: dict[str, object]) -> None:
            if message.get("type") == "set_model":
                self.state["model"] = {
                    **MODEL,
                    "provider": message["provider"],
                    "id": message["modelId"],
                }
            await super().send(message)

    pi = SelectedPi()
    pi.models = [{**MODEL, "provider": "deepseek", "id": "native-model"}]
    report = await run_pi(
        pi,
        task="Work",
        timeout_seconds=1,
        shown=ignore,
        key_provider="deepseek",
        model="deepseek/native-model",
    )
    assert report.outcome == "completed"
    assert report.credentials is not None and report.credentials.source == "vault"
    assert (
        next(message for message in pi.seen if message["type"] == "set_model")["modelId"]
        == "native-model"
    )
    for model in [None, "other/native-model", "deepseek/native-model"]:
        pi = Pi()
        with pytest.raises(AcpError):
            await run_pi(
                pi,
                task="Work",
                timeout_seconds=1,
                shown=ignore,
                key_provider="deepseek",
                model=model,
            )
        assert not any(message["type"] == "prompt" for message in pi.seen)


async def test_catalogs_keep_the_selected_provider_and_report_bounded_results() -> None:
    pi = Pi()
    pi.state["model"] = {**MODEL, "provider": "deepseek", "id": "last"}
    pi.models = [{**MODEL, "provider": "deepseek", "id": f"m-{index}"} for index in range(129)] + [
        pi.state["model"],
        MODEL,
    ]
    catalog = await inspect_pi(pi, timeout_seconds=1, key_provider="deepseek")
    assert catalog.models_truncated and len(catalog.models) == 128
    assert catalog.models[0].id == "deepseek/last"
    assert all(model.id.startswith("deepseek/") for model in catalog.models)
    assert catalog.configuration_policy == "session"
    pi = Pi()
    with pytest.raises(AcpError, match="another provider"):
        await inspect_pi(pi, timeout_seconds=1, key_provider="deepseek")


def test_a_catalog_never_returns_a_selected_key_even_as_a_model_identity() -> None:
    catalog = AcpCatalog(models=[AcpChoice(id="selected-private-key", name="Private")])
    with pytest.raises(AcpError, match="credential material"):
        catalog_json(catalog, key())
    assert json.loads(catalog_json(catalog, None))["models"][0]["name"] == "Private"


async def test_the_real_native_tool_path_never_streams_or_reports_the_selected_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_core import to_jsonable_python

    from app.agents.capabilities.external_acp._capability import ExternalAcp
    from app.services.device_hub import workspace as workspace_module
    from tests.test_pi_rpc import finished

    class SelectedPi(Pi):
        async def send(self, message: dict[str, object]) -> None:
            if message.get("type") == "set_model":
                self.state["model"] = {
                    **MODEL,
                    "provider": message["provider"],
                    "id": message["modelId"],
                }
            await super().send(message)

    pi = SelectedPi(
        [
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "selected-"},
            },
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "private-key"},
            },
            {
                "type": "tool_execution_start",
                "toolCallId": "selected-private-key",
                "toolName": "Read selected-private-key",
            },
            {"type": "tool_execution_end", "toolCallId": "selected-private-key"},
            finished("Done with selected-private-key"),
            {"type": "agent_settled"},
        ]
    )
    pi.models = [{**MODEL, "provider": "deepseek", "id": "native-model"}]
    launched: dict[str, object] = {}
    cursor = 0

    async def call(
        _session_id: object, op: str, args: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        nonlocal cursor
        if op == "agent.open":
            launched.update(args)
            return {
                "id": "owned",
                "protocol": "pi_rpc",
                "pi_provider": "deepseek",
                "runtime_name": "My Pi",
            }
        if op == "agent.send":
            await pi.send(args["message"])
        if op == "agent.poll":
            lines = [json.dumps(message) for message in pi.messages]
            pi.messages.clear()
            cursor += len(lines)
            return {"lines": lines, "cursor": cursor, "exit": None}
        if op == "agent.close":
            await pi.close()
        return {}

    monkeypatch.setattr(workspace_module._hub, "call", call)
    monkeypatch.setattr(
        "app.agents.capabilities.external_acp._toolset.selected_key", AsyncMock(return_value=key())
    )
    frames = []
    context = _ctx(_local_workspace(), frames)
    function = (
        ExternalAcp(
            "pi-key", api_provider="deepseek", secret_id=uuid4(), model_id="deepseek/native-model"
        )
        .get_toolset()
        .tools["run_acp_agent"]
        .function
    )
    result = await function(context, task="Work")
    assert launched["pi_key"] == key().native_payload("deepseek/native-model")
    assert "selected-private-key" not in result
    assert json.loads(result)["answer"] == "Done with [redacted]"
    streamed = json.dumps(to_jsonable_python(frames))
    assert "selected-" not in streamed and "private-key" not in streamed
    assert pi.closed


async def test_a_selected_key_cannot_launch_without_an_exact_model() -> None:
    device = FakeDevice([])
    pipe = DevicePipe(device, "custom", custom_agent_id="pi-key", pi_key=key())
    with pytest.raises(AcpError, match="exact model ID"):
        await pipe.open()
    assert not device.calls


@pytest.mark.parametrize("models", [None, [{"provider": "deepseek"}]])
async def test_selected_key_rejects_malformed_native_catalog_before_inference(
    models: object,
) -> None:
    pi = Pi()
    pi.models = models
    with pytest.raises(AcpError, match="unsupported model catalog"):
        await run_pi(
            pi,
            task="Work",
            timeout_seconds=1,
            shown=ignore,
            key_provider="deepseek",
            model="deepseek/native-model",
        )
    assert pi.closed
    assert not any(message["type"] == "prompt" for message in pi.seen)


async def test_a_listed_model_does_not_replace_the_required_native_state_acknowledgement() -> None:
    pi = Pi()
    pi.models = [{**MODEL, "provider": "deepseek", "id": "native-model"}]
    with pytest.raises(AcpError, match="did not acknowledge"):
        await run_pi(
            pi,
            task="Work",
            timeout_seconds=1,
            shown=ignore,
            key_provider="deepseek",
            model="deepseek/native-model",
        )
    assert pi.closed
    assert any(message["type"] == "set_model" for message in pi.seen)
    assert not any(message["type"] == "prompt" for message in pi.seen)


async def test_a_gemini_keyed_delegation_screens_questions_and_forwards_platform_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.audience import RunAudience
    from app.agents.capabilities.coding_agent import _toolset as coding_toolset
    from app.agents.capabilities.coding_agent._harness import CodingReport
    from app.agents.capabilities.external_acp._capability import ExternalAcp
    from app.agents.runtime_questions import RuntimeQuestionResponse
    from app.services.device_hub import workspace as workspace_module
    from tests.test_runtime_tools import bridge

    gemini = NativeRuntimeKey(provider="gemini", api_key="AIza-private-key", revision="d" * 64)
    launched: dict[str, object] = {}

    async def call(_session_id: object, op: str, args: dict[str, object], *, timeout: float):
        if op == "agent.open":
            launched.update(args)
            return {
                "id": "owned",
                "protocol": "acp",
                "gemini_key": True,
                "platform_tools_version": 1,
            }
        return {}

    seen: list[object] = []

    async def run(pipe, **options) -> CodingReport:
        seen.append(options["platform_tools"])
        leaking = MagicMock()
        leaking.model_dump_json.return_value = '{"title": "AIza-private-key"}'
        with pytest.raises(AcpError, match="credential material"):
            await options["runtime_questions"](leaking)
        clean = MagicMock()
        clean.model_dump_json.return_value = '{"title": "Continue?"}'
        seen.append(await options["runtime_questions"](clean))
        return CodingReport(
            harness="custom", access="edit", outcome="completed", answer="", session_id="s"
        )

    monkeypatch.setattr(workspace_module._hub, "call", call)
    monkeypatch.setattr(
        "app.agents.capabilities.external_acp._toolset.selected_key", AsyncMock(return_value=gemini)
    )
    monkeypatch.setattr(coding_toolset, "run_task", run)
    context = _ctx(_local_workspace(), [])
    person = context.workspace.backend.owner_id
    context.deps.run_person = person
    context.deps.user_id = str(person)
    context.deps.audience = RunAudience(user_id=person)
    tools, _calls = await bridge()
    context.tool_manager = tools._ctx.tool_manager
    function = (
        ExternalAcp("agy-key", api_provider="gemini", secret_id=uuid4(), platform_tools=True)
        .get_toolset()
        .tools["run_acp_agent"]
        .function
    )
    result = await function(context, task="Work")
    assert launched["gemini_key"] == "AIza-private-key" and launched["platform_tools"] is True
    assert seen[0] is not None
    assert seen[1] == RuntimeQuestionResponse(cancelled=True)
    assert "AIza-private-key" not in result and json.loads(result)["outcome"] == "completed"


def test_a_pi_key_lane_with_its_own_provider_model_is_accepted() -> None:
    config = ExternalAcpConfig.model_validate(
        {"agent_id": "pi-key", "api_provider": "deepseek", "model_id": "deepseek/chat"}
    )
    assert config.model_id == "deepseek/chat"


@pytest.mark.parametrize("change", ["shared", "no_audience", "other_person", "cloud"])
async def test_forwarded_platform_tools_need_the_initiators_private_computer(change: str) -> None:
    from dataclasses import replace as replaced

    from app.agents.audience import RunAudience
    from app.agents.capabilities.external_acp._capability import ExternalAcp

    context = _ctx(_local_workspace(), [])
    person = context.workspace.backend.owner_id
    context.deps.run_person = person
    context.deps.user_id = str(person)
    context.deps.audience = RunAudience(user_id=person)
    if change == "shared":
        context.deps.audience = replaced(context.deps.audience, shared_transcript=True)
    elif change == "no_audience":
        context.deps.audience = None
    elif change == "other_person":
        context.deps.audience = RunAudience(user_id=uuid4())
    else:
        context = replaced(context, workspace=MagicMock(attached=False))
    function = ExternalAcp("agy", platform_tools=True).get_toolset().tools["run_acp_agent"].function
    from pydantic_ai.exceptions import ModelRetry

    with pytest.raises(ModelRetry, match="private approved computer"):
        await function(context, task="Work")
