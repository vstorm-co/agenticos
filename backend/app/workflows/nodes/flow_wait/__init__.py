"""`flow.wait` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.flow_wait._handler import (
    FlowWaitConfig,
    FlowWaitInput,
    FlowWaitOutput,
    handle,
)

__all__ = ["FlowWaitConfig", "FlowWaitInput", "FlowWaitOutput"]

register(
    NodeDefinition(
        id="flow.wait",
        version=1,
        name="Wait",
        category="control",
        description="Hold the run for a while, or until a time, then go on.",
        kind="action",
        config_schema=FlowWaitConfig,
        input_schema=FlowWaitInput,
        output_schema=FlowWaitOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=FlowWaitOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
