"""`workflow.run` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.workflow_run._handler import (
    WorkflowRunConfig,
    WorkflowRunInput,
    WorkflowRunOutput,
    check_resources,
    handle,
)

__all__ = ["WorkflowRunConfig", "WorkflowRunInput", "WorkflowRunOutput"]

register(
    NodeDefinition(
        id="workflow.run",
        version=1,
        name="Run a workflow",
        category="control",
        description="Run another workflow as a step, and hand on what it answers.",
        kind="action",
        config_schema=WorkflowRunConfig,
        input_schema=WorkflowRunInput,
        output_schema=WorkflowRunOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=WorkflowRunOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
    )
)
