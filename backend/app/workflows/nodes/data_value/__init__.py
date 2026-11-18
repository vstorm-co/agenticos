"""`data.value` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.data_value._handler import DataValueInput, DataValueOutput, handle

__all__ = ["DataValueInput", "DataValueOutput"]

register(
    NodeDefinition(
        id="data.value",
        version=1,
        name="Data",
        category="data",
        description="Hold an object, a list or a value for later steps. Set once per run.",
        kind="action",
        config_schema=None,
        input_schema=DataValueInput,
        output_schema=DataValueOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=DataValueOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
