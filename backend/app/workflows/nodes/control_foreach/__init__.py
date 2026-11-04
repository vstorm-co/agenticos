"""`control.foreach` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.control_foreach._handler import (
    BODY_PORT,
    DONE_PORT,
    ForeachConfig,
    ForeachInput,
    ForeachItemError,
    ForeachManifest,
    ForeachOutput,
    handle,
    routes,
)

__all__ = [
    "BODY_PORT",
    "DONE_PORT",
    "ForeachConfig",
    "ForeachInput",
    "ForeachItemError",
    "ForeachManifest",
    "ForeachOutput",
]

register(
    NodeDefinition(
        id="control.foreach",
        version=1,
        name="For each",
        category="control",
        description="Run the steps inside the loop once for every item in a list, in order.",
        kind="control",
        config_schema=ForeachConfig,
        input_schema=ForeachInput,
        output_schema=ForeachOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id=BODY_PORT, label="Each item", kind="output", schema=None),
            Port(id=DONE_PORT, label="Done", kind="output", schema=ForeachOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
    )
)
