"""`core.input` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.nodes.core_input._handler import handle

register(
    NodeDefinition(
        id="core.input",
        version=1,
        name="Input",
        category="core",
        description="Where the workflow starts: the payload the run was started with.",
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
