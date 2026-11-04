"""Runs and MCP explain actual native access without inventing new grants."""

import pytest

from app.agents.spec import AgentSpec
from app.schemas.local_target import LocalTarget
from app.services.agent_runner import _with_execution_environment
from app.services.agent_templates import APP_ENVIRONMENT_GUIDANCE
from app.services.platform_mcp import INSTRUCTIONS


@pytest.mark.parametrize(
    "target",
    [
        None,
        LocalTarget(folder="/approved", mode="read_only"),
        LocalTarget(folder="/approved", mode="workspace_write"),
        LocalTarget(folder="/approved", mode="full_access"),
        LocalTarget(browser=True),
        LocalTarget(
            folder="/approved", browser=True, model_service="ollama", mcp_services=["docs"]
        ),
    ],
)
def test_runtime_explains_selected_resources_without_changing_the_agent(
    target: LocalTarget | None,
) -> None:
    spec = AgentSpec(name="Helper", instructions="Do the job.")
    actual = _with_execution_environment(spec, target)
    assert _with_execution_environment(actual, target) is actual
    assert spec.instructions == "Do the job."
    assert actual.capabilities == spec.capabilities
    assert APP_ENVIRONMENT_GUIDANCE in actual.instructions
    assert "not uploaded, synchronized" in actual.instructions
    assert "does not provide a desktop shell" in actual.instructions
    assert ("### Selected for this run" in actual.instructions) is (target is not None)
    if target is not None:
        assert ("Sandbox tools use" in actual.instructions) is (target.folder is not None)
        assert (
            "Browser tools use the approved local browser" in actual.instructions
        ) is target.browser
        assert ("Inference uses the selected local model service" in actual.instructions) is (
            target.model_service is not None
        )
        assert ("services are available through this run" in actual.instructions) is bool(
            target.mcp_services
        )
        assert "/approved" not in actual.instructions


def test_mcp_carries_the_same_environment_facts_without_claiming_device_access() -> None:
    assert APP_ENVIRONMENT_GUIDANCE in INSTRUCTIONS
    assert "cannot grant native" in INSTRUCTIONS
    assert "Mobile" in INSTRUCTIONS
