"""The workflows capability's registration: what it builds from a binding, and what it refuses."""

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.agents.capabilities._members import acting_member
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.workflows import Workflows, WorkflowsConfig


def _built(config: WorkflowsConfig | None):
    return get("workflows").builder(
        CapabilityBuildContext(binding=CapabilityBinding(capability_id="workflows"), config=config)
    )


def test_a_binding_naming_no_workflow_builds_nothing():
    assert _built(None) is None
    assert _built(WorkflowsConfig()) is None


def test_a_binding_builds_the_workflows_it_names_and_how_long_it_waits():
    named = uuid.uuid4()

    built = _built(WorkflowsConfig(workflow_ids=[named], wait_seconds=30))

    assert isinstance(built, Workflows)
    assert (built.workflow_ids, built.wait_seconds) == ((named,), 30)
    assert built.get_toolset() is built.get_toolset()
    assert set(built.get_toolset().tools) == {"list_workflows", "run_workflow", "get_workflow_run"}


@pytest.mark.parametrize(
    "config",
    [
        {"workflow_ids": [str(uuid.UUID(int=1))] * 2},
        {"wait_seconds": 1},
        {"wait_seconds": 301},
    ],
)
def test_a_config_outside_the_limits_is_refused(config):
    with pytest.raises(ValidationError):
        WorkflowsConfig.model_validate(config)


@pytest.mark.anyio
async def test_the_acting_member_is_nobody_for_a_run_without_a_member_id():
    assert await acting_member(MagicMock(), None, "x") is None
    assert await acting_member(MagicMock(), uuid.uuid4(), None) is None
    assert await acting_member(MagicMock(), uuid.uuid4(), "not-a-uuid") is None
