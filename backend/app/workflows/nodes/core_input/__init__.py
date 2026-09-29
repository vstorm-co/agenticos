"""`core.input` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.nodes.core_input._handler import handle
from app.workflows.triggers import MANUAL

register(
    NodeDefinition(
        id=MANUAL,
        version=1,
        name="Manual or API",
        category=TRIGGER_CATEGORY,
        description="Start by hand, from the API or over a WebSocket, with the payload you give.",
        kind="action",
        config_schema=None,
        input_schema=None,
        output_schema=WorkflowInputPayload,
        ports=(Port(id="out", label="Out", kind="output", schema=WorkflowInputPayload),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
