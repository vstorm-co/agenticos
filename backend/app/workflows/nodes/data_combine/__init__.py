"""`data.combine` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.data_combine._handler import (
    DataCombineConfig,
    DataCombineInput,
    DataCombineOutput,
    handle,
)

__all__ = ["DataCombineConfig", "DataCombineInput", "DataCombineOutput"]

register(
    NodeDefinition(
        id="data.combine",
        version=1,
        name="Combine lists",
        category="data",
        description="Make one list of two: one after the other, by position or by a key.",
        kind="action",
        config_schema=DataCombineConfig,
        input_schema=DataCombineInput,
        output_schema=DataCombineOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=DataCombineOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
