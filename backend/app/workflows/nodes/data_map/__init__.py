"""`data.map` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.data_map._handler import (
    DataMapConfig,
    DataMapInput,
    DataMapOutput,
    FieldMapping,
    coerce,
    handle,
)

__all__ = ["DataMapConfig", "DataMapInput", "DataMapOutput", "FieldMapping", "coerce"]

register(
    NodeDefinition(
        id="data.map",
        version=1,
        name="Map fields",
        category="data",
        description="Pick values out of earlier outputs and give each one a type.",
        kind="action",
        config_schema=DataMapConfig,
        input_schema=DataMapInput,
        output_schema=DataMapOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=DataMapOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
