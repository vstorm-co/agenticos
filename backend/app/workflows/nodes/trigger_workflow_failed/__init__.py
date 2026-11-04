"""`trigger.workflow_failed` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import WorkflowFailedTriggerOutput
from app.workflows.nodes.trigger_workflow_failed._handler import handle
from app.workflows.triggers import WORKFLOW_FAILED

register(
    NodeDefinition(
        id=WORKFLOW_FAILED,
        version=1,
        name="On failure of a workflow",
        category=TRIGGER_CATEGORY,
        description="A run of a workflow that names this one as its error workflow fails.",
        kind="action",
        config_schema=None,
        input_schema=None,
        output_schema=WorkflowFailedTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=WorkflowFailedTriggerOutput),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
