"""`debug.relay` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.debug_echo import DebugEchoConfig, DebugEchoOutput
from app.workflows.nodes.debug_relay._handler import handle

register(
    NodeDefinition(
        id="debug.relay",
        version=1,
        name="Relay",
        category="debug",
        description="Passes an echoed message on as a plain message. Has no real effect.",
        kind="action",
        config_schema=None,
        input_schema=DebugEchoOutput,
        output_schema=DebugEchoConfig,
        ports=(
            Port(id="in", label="In", kind="input", schema=DebugEchoOutput),
            Port(id="out", label="Out", kind="output", schema=DebugEchoConfig),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
