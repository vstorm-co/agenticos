"""`core.output` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.io import WorkflowOutputPayload
from app.workflows.nodes.core_output._handler import handle

register(
    NodeDefinition(
        id="core.output",
        version=1,
        name="Output",
        category="core",
        description="What the workflow answers: text, sources, files and a structured value.",
        kind="action",
        config_schema=None,
        input_schema=WorkflowOutputPayload,
        output_schema=WorkflowOutputPayload,
        ports=(Port(id="in", label="In", kind="input", schema=None),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
