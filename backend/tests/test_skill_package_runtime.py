"""Imported frontmatter never adds tools or bypasses native approval handling."""

from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.skills import Skills
from app.agents.capabilities.skills._loader import ReadSkillReturnPart, SkillLoader
from app.db.models.skill import Skill, SkillResource
from app.services.skill_workspace import render_body

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def package_skill() -> Skill:
    return Skill(
        id=uuid4(),
        name="proposal-builder",
        description="Prepare proposals.",
        content="Use the template.",
        manifest_metadata={
            "license": "MIT",
            "allowed-tools": ["execute", "dangerous_action"],
            "metadata": {"version": "one"},
        },
        resources=[
            SkillResource(name="references/check.md", content="Check facts.", encoding="utf8")
        ],
    )


def loaded(messages: list[ModelMessage]) -> bool:
    return any(
        isinstance(part, ReadSkillReturnPart) for message in messages for part in message.parts
    )


async def test_actual_native_skill_loading_cannot_enable_unbound_tools() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        names = {tool.name for tool in info.function_tools}
        assert "execute" not in names
        assert "dangerous_action" not in names
        assert "run_skill_script" not in names
        if loaded(messages):
            assert "read_skill_resource" in names
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "proposal-builder"})])

    result = await Agent(
        FunctionModel(model), capabilities=[SkillLoader(), Skills([package_skill()])]
    ).run("Prepare a proposal")
    assert result.output == "done"


async def test_allowed_tools_metadata_cannot_skip_always_ask() -> None:
    calls: list[str] = []
    tools = FunctionToolset()

    @tools.tool_plain(requires_approval=True)
    def dangerous_action() -> str:
        """A bound action whose approval must remain required."""
        calls.append("executed")
        return "done"

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if loaded(messages):
            assert "dangerous_action" in {tool.name for tool in info.function_tools}
            return ModelResponse(parts=[ToolCallPart("dangerous_action", {})])
        return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "proposal-builder"})])

    agent = Agent(
        FunctionModel(model),
        output_type=[str, DeferredToolRequests],
        toolsets=[tools],
        capabilities=[SkillLoader(), Skills([package_skill()])],
    )
    result = await agent.run("Do the action")
    assert isinstance(result.output, DeferredToolRequests)
    assert [call.tool_name for call in result.output.approvals] == ["dangerous_action"]
    assert calls == []


async def test_canonical_root_yaml_preserves_extras_and_escapes_metadata() -> None:
    from app.services.skill_library import split_frontmatter

    skill = package_skill()
    skill.description = "Notes: safely quoted\nwith another line"
    metadata, instructions = split_frontmatter(render_body(skill))
    assert metadata["name"] == skill.name
    assert metadata["description"] == skill.description
    assert metadata["license"] == "MIT"
    assert metadata["allowed-tools"] == ["execute", "dangerous_action"]
    assert instructions.strip() == skill.content
