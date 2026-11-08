"""The workflows capability's registration: what it builds from a binding, and what it refuses."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.workflows import Workflows, WorkflowsConfig, _toolset
from app.agents.capabilities.workflows._toolset import (
    MAX_DISCOVERY_BYTES,
    _inputs,
    build_workflows_toolset,
)
from app.agents.deps import AgentDeps
from app.db.models.workflow import Workflow, WorkflowStatus
from app.services.access import acting_member


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


@pytest.mark.anyio
async def test_workflow_tool_discovery_preserves_schema_references_and_legacy_fields() -> None:
    workflow = MagicMock(organization_id=uuid.uuid4())
    entry = str(uuid.uuid4())
    schema = {
        "$defs": {"text": {"type": "string", "minLength": 2}},
        "properties": {"name": {"$ref": "#/$defs/text"}},
    }
    graph = {
        "entry_node_id": entry,
        "nodes": [
            {"id": entry, "definition_id": "trigger.manual", "config": {"input_schema": schema}}
        ],
    }
    version = MagicMock(graph=graph)
    with patch(
        "app.agents.capabilities.workflows._toolset.workflow_repo.get_version",
        new=AsyncMock(return_value=version),
    ):
        fields, contract = await _inputs(MagicMock(), workflow, uuid.uuid4())
        assert fields == [] and contract == schema
        graph["nodes"][0]["config"] = {
            "fields": [{"name": "name", "type": "text", "required": True}]
        }
        fields, contract = await _inputs(MagicMock(), workflow, uuid.uuid4())
        assert fields == [{"name": "name", "type": "text", "required": True}]
        assert contract["required"] == ["name"] and contract["additionalProperties"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("missing", [False, True])
async def test_workflow_tool_discovery_keeps_untyped_workflows_open(missing: bool) -> None:
    workflow = MagicMock(organization_id=uuid.uuid4())
    version = None if missing else MagicMock(graph={"nodes": []})
    with patch(
        "app.agents.capabilities.workflows._toolset.workflow_repo.get_version",
        new=AsyncMock(return_value=version),
    ):
        assert await _inputs(MagicMock(), workflow, uuid.uuid4()) == ([], {"type": "object"})


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("count", "character", "length"),
    [
        (1, "x", MAX_DISCOVERY_BYTES),
        (1, "界", MAX_DISCOVERY_BYTES // 2),
        (2, "x", MAX_DISCOVERY_BYTES // 2),
    ],
)
async def test_tool_discovery_refuses_oversized_contracts_without_partial_output(
    count: int, character: str, length: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization_id = uuid.uuid4()
    workflows = [
        Workflow(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name="Published workflow",
            status=WorkflowStatus.PUBLISHED.value,
            current_version_id=uuid.uuid4(),
            live_trigger="core.input",
            live_triggers=["core.input"],
        )
        for _ in range(count)
    ]
    by_id = {workflow.id: workflow for workflow in workflows}

    async def get_workflow(
        db: object, workflow_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> Workflow | None:
        return by_id.get(workflow_id)

    entry_id = str(uuid.uuid4())
    config = {"input_schema": {"description": character * length}}
    version = MagicMock(
        graph={
            "entry_node_id": entry_id,
            "nodes": [{"id": entry_id, "definition_id": "core.input", "config": config}],
        }
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=MagicMock())
    actor = MagicMock(organization_id=organization_id)
    ctx = RunContext(
        deps=AgentDeps(organization_id=organization_id, user_id=str(uuid.uuid4())),
        model=TestModel(),
        usage=RunUsage(),
    )
    toolset = build_workflows_toolset(workflow_ids=tuple(by_id), wait_seconds=0)
    discover = toolset.tools["list_workflows"].function
    with (
        patch.object(_toolset, "get_db_context", return_value=context),
        patch.object(_toolset, "acting_member", new=AsyncMock(return_value=actor)),
        patch.object(_toolset.workflow_repo, "get", new=get_workflow),
        patch.object(_toolset.workflow_repo, "get_version", new=AsyncMock(return_value=version)),
        patch.object(_toolset, "resolve_access", new=AsyncMock(return_value=True)),
    ):
        refused = await discover(ctx)
        assert "32 KiB allowance" in refused
        assert len(refused.encode()) < MAX_DISCOVERY_BYTES
        assert character * length not in refused
        config["input_schema"] = {"type": "object"}
        accepted = await discover(ctx)
        assert len(json.loads(accepted)) == count
        monkeypatch.setattr(_toolset, "MAX_DISCOVERY_BYTES", len(accepted.encode()))
        assert await discover(ctx) == accepted
        monkeypatch.setattr(_toolset, "MAX_DISCOVERY_BYTES", len(accepted.encode()) - 1)
        assert "32 KiB allowance" in await discover(ctx)
