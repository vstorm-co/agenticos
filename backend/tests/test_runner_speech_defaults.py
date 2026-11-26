"""Shared voices resolve before construction and remain fixed on resume."""

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec, SpecialistSpec, SubagentRef
from app.agents.subagent_runtime import SUBAGENT_RUNTIME_RESOURCE, SubagentRuntime
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.organization import Organization
from app.schemas.organization import OrganizationTextToSpeech
from app.services.agent_runner import AgentRunnerService
from tests.test_agent_runner import (
    _ctx,
    _db,
    _parked_run,
    _resolved_model,
)
from tests.test_agent_runner import (
    _in_no_group as _in_no_group,
)
from tests.test_agent_runner import (
    _no_connected_chat_bindings as _no_connected_chat_bindings,
)
from tests.test_agent_runner import (
    _no_conversation_shares as _no_conversation_shares,
)
from tests.test_agent_runner import (
    _no_current_cap as _no_current_cap,
)
from tests.test_agent_runner import (
    _nobody_the_account_describes as _nobody_the_account_describes,
)

pytestmark = pytest.mark.anyio
RUNNER = "app.services.agent_runner"


@dataclass
class SpeechRun:
    service: AgentRunnerService
    ctx: AuthContext
    agent: Agent
    spec: AgentSpec
    org: Organization
    defaults: OrganizationTextToSpeech
    run: AgentRun
    runnable: AsyncMock
    created: AsyncMock
    factory: MagicMock
    secrets: AsyncMock


@pytest.fixture
def speech_run() -> Iterator[SpeechRun]:
    ctx = _ctx()
    defaults = OrganizationTextToSpeech(
        provider="openai", model="gpt-4o-mini-tts", voice="coral", secret_id=uuid4()
    )
    org = Organization(id=ctx.organization_id, text_to_speech=defaults.model_dump(mode="json"))
    agent = Agent(id=uuid4(), kind="agent", current_version_id=uuid4(), name="Narrator")
    spec = AgentSpec(name="Narrator", model_profile_id=uuid4(), capabilities=[inherited_voice()])
    run = AgentRun(id=uuid4(), organization_id=ctx.organization_id, agent_id=agent.id)
    service = AgentRunnerService(_db())
    with ExitStack() as stack:
        runnable = stack.enter_context(
            patch.object(
                service.registry,
                "get_runnable_spec",
                AsyncMock(return_value=(agent, spec, agent.current_version_id)),
            )
        )
        stack.enter_context(
            patch.object(
                service.models, "resolve", AsyncMock(return_value=_resolved_model("gpt-4.1"))
            )
        )
        stack.enter_context(
            patch.object(service.skills, "resolve_for_agent", AsyncMock(return_value=[]))
        )
        secrets = stack.enter_context(
            patch.object(service.secrets, "resolve_for_bindings", AsyncMock(return_value={}))
        )
        created = stack.enter_context(
            patch(f"{RUNNER}.agent_run_repo.create_run", AsyncMock(return_value=run))
        )
        factory = stack.enter_context(patch(f"{RUNNER}.build_agent"))
        stack.enter_context(
            patch(
                "app.services.text_to_speech_settings.organization_repo.get_by_id",
                AsyncMock(return_value=org),
            )
        )
        stack.enter_context(
            patch(
                "app.services.text_to_speech_settings.provider_keys.key_problem",
                AsyncMock(return_value=None),
            )
        )
        stack.enter_context(
            patch(
                "app.services.agent_registry.organization_assistant_repo.for_agent",
                AsyncMock(return_value=None),
            )
        )
        yield SpeechRun(
            service, ctx, agent, spec, org, defaults, run, runnable, created, factory, secrets
        )


def inherited_voice() -> CapabilityBindingSpec:
    return CapabilityBindingSpec(id="text_to_speech", config={"use_organization_defaults": True})


def assert_voice(spec: AgentSpec, *, key: UUID) -> None:
    binding = next(binding for binding in spec.capabilities if binding.id == "text_to_speech")
    assert binding.config["provider"] == "openai"
    assert binding.config["model"] == "gpt-4o-mini-tts"
    assert binding.config["voice"] == "coral"
    assert binding.config["use_organization_defaults"] is False
    assert binding.secret_id == key


async def test_preparation_pins_the_voice_group_before_the_factory_can_use_it(
    speech_run: SpeechRun,
) -> None:
    state = speech_run
    prepared = await state.service.prepare(state.ctx, state.agent.id)
    assert state.created.await_args.kwargs["text_to_speech_defaults"] == state.defaults.model_dump(
        mode="json"
    )
    assert_voice(prepared.spec, key=state.defaults.secret_id)
    assert_voice(state.factory.call_args.args[0], key=state.defaults.secret_id)
    assert state.secrets.await_args.args[1] == [state.defaults.secret_id]
    assert state.spec.capabilities[0].config == {"use_organization_defaults": True}


@pytest.mark.parametrize("snapshot", [True, False])
async def test_resume_uses_the_recorded_voice_or_resolves_an_older_unpinned_run(
    speech_run: SpeechRun, snapshot: bool
) -> None:
    state = speech_run
    state.org.text_to_speech = state.defaults.model_copy(update={"voice": "alloy"}).model_dump(
        mode="json"
    )
    run = _parked_run(
        user_id=state.ctx.user_id,
        text_to_speech_defaults=state.defaults.model_dump(mode="json") if snapshot else None,
    )
    prepared = await state.service._assemble(
        state.ctx,
        agent=state.agent,
        spec=state.spec,
        existing_run=run,
        surface=RunSurface.API,
        conversation_id=None,
        user_name=None,
        extra_toolsets=None,
        exposure=None,
        decided={},
        resuming={},
        already_spent={},
        already_started={},
    )
    voice = prepared.spec.capabilities[0]
    assert voice.config["voice"] == ("coral" if snapshot else "alloy")
    assert voice.secret_id == state.defaults.secret_id
    state.created.assert_not_awaited()


@pytest.mark.security
async def test_disabling_shared_speech_refuses_an_approved_run_before_factory_construction(
    speech_run: SpeechRun,
) -> None:
    state = speech_run
    state.org.text_to_speech = state.defaults.model_copy(update={"enabled": False}).model_dump(
        mode="json"
    )
    with pytest.raises(BadRequestError, match="disabled"):
        await state.service._assemble(
            state.ctx,
            agent=state.agent,
            spec=state.spec,
            existing_run=_parked_run(
                text_to_speech_defaults=state.defaults.model_dump(mode="json")
            ),
            surface=RunSurface.API,
            conversation_id=None,
            user_name=None,
            extra_toolsets=None,
            exposure=None,
            decided={},
            resuming={},
            already_spent={},
            already_started={},
        )
    state.factory.assert_not_called()
    state.secrets.assert_not_awaited()


@pytest.mark.parametrize("published", [False, True])
async def test_a_voice_only_on_a_delegate_pins_the_parent_run_before_the_delegate_builds(
    speech_run: SpeechRun, published: bool
) -> None:
    state = speech_run
    specialist = SpecialistSpec(
        name="narrator",
        description="Read aloud",
        instructions="Speak.",
        capabilities=[inherited_voice()],
    )
    delegate = Agent(id=uuid4(), kind="agent", name="Narrator", slug="narrator", status="published")
    version = AgentVersion(
        id=uuid4(),
        agent_id=delegate.id,
        spec=AgentSpec(name="Narrator", capabilities=[inherited_voice()]).model_dump(mode="json"),
    )
    spec = AgentSpec(
        name="Coordinator",
        capabilities=[
            CapabilityBindingSpec(
                id="subagents",
                config={"inline": [] if published else [specialist.model_dump(mode="json")]},
            )
        ],
        subagents=[SubagentRef(agent_id=delegate.id, agent_version_id=version.id)]
        if published
        else [],
    )
    state.runnable.return_value = (state.agent, spec, state.agent.current_version_id)
    with (
        patch(f"{RUNNER}.agent_repo.get", AsyncMock(return_value=delegate)),
        patch(f"{RUNNER}.agent_repo.get_version", AsyncMock(return_value=version)),
    ):
        prepared = await state.service.prepare(state.ctx, state.agent.id)
    assert state.run.text_to_speech_defaults == state.defaults.model_dump(mode="json")
    runtime = state.factory.call_args.kwargs["resources"][SUBAGENT_RUNTIME_RESOURCE]
    assert isinstance(runtime, SubagentRuntime)
    resolved = runtime.named("narrator")
    assert resolved is not None
    with patch(f"{RUNNER}.build_agent", state.factory):
        resolved.build()
    assert_voice(state.factory.call_args.args[0], key=state.defaults.secret_id)
    assert prepared.spec.capabilities[0].id == "subagents"


@pytest.mark.parametrize("scope", ["private", "room", "edit-share"])
async def test_preparation_records_the_current_shared_history_boundary(
    speech_run: SpeechRun, scope: str
) -> None:
    state = speech_run
    with patch.object(
        state.service, "_shared_for_editing", AsyncMock(return_value=scope == "edit-share")
    ):
        prepared = await state.service.prepare(
            state.ctx,
            state.agent.id,
            conversation_id=uuid4(),
            memory_room_key="room:mattermost:team" if scope == "room" else None,
        )
    assert prepared.shared_history is (scope != "private")
