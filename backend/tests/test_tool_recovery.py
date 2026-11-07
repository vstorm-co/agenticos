"""Recovery guidance reaches the model independently of an agent author's prompt."""

from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.agents.tool_recovery import ToolRecovery
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio


async def test_recovery_instructions_reach_the_model_alongside_the_agents_task() -> None:
    seen: list[str] = []

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert info.instructions is not None
        seen.append(info.instructions)
        return ModelResponse(parts=[TextPart("done")])

    agent = Agent(
        FunctionModel(respond),
        instructions="Help investigate network devices.",
        capabilities=[ToolRecovery()],
    )

    await agent.run("Find the device")

    (instructions,) = seen
    assert "Help investigate network devices." in instructions
    assert "correct the specified field" in instructions
    assert "Do not repeat the same invalid arguments." in instructions
    assert "runtime or discovery result explicitly establishes it" in instructions
    assert "Do not infer missing user permission from a tool-registration error." in instructions
    assert "workflow lookup failure does not justify filesystem searches" in instructions
    assert "check execution status before retrying an action" in instructions
    assert "stop automatic retries" in instructions
    assert "code=invalid_arguments and cause_execution=not_started" in instructions
    assert "earlier actions before replaying the script" in instructions
    assert "error ID" in instructions


def test_every_built_agent_carries_recovery_guidance_without_a_spec_binding() -> None:
    built = build_agent(
        AgentSpec(name="Network helper"),
        ModelRequestSpec(
            profile_id=uuid4(),
            label="Test",
            provider="openai",
            model="gpt-4.1",
            params={},
            fallbacks=[],
            credential=ResolvedCredential(
                provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
            ),
        ),
        organization_id=uuid4(),
    )
    attached: list[object] = []
    built.agent.root_capability.apply(attached.append)

    assert len([capability for capability in attached if isinstance(capability, ToolRecovery)]) == 1
