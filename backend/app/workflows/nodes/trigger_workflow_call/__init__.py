"""`trigger.workflow_call` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.nodes.trigger_workflow_call._handler import (
    STATIC_PORTS,
    TriggerInputConfig,
    handle,
    ports_for,
)
from app.workflows.triggers import WORKFLOW_CALL

register(
    NodeDefinition(
        id=WORKFLOW_CALL,
        version=1,
        name="Called by a workflow",
        category=TRIGGER_CATEGORY,
        description="Another workflow's Run a workflow step starts it with the fields it declares.",
        kind="action",
        config_schema=TriggerInputConfig,
        input_schema=None,
        output_schema=WorkflowInputPayload,
        ports=STATIC_PORTS,
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        ports_for=ports_for,
    )
)
