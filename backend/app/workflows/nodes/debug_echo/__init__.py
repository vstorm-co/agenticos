"""`debug.echo` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.debug_echo._handler import DebugEchoConfig, DebugEchoOutput, handle

__all__ = ["DebugEchoConfig", "DebugEchoOutput"]

register(
    NodeDefinition(
        id="debug.echo",
        version=1,
        name="Echo",
        category="debug",
        description="Echoes its input back, unchanged. Has no real effect.",
        kind="action",
        config_schema=DebugEchoConfig,
        input_schema=DebugEchoConfig,
        output_schema=DebugEchoOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=DebugEchoConfig),
            Port(id="out", label="Out", kind="output", schema=DebugEchoOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
