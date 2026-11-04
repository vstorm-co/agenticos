"""`data.filter` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.data_filter._handler import (
    DataFilterConfig,
    DataFilterInput,
    DataFilterOutput,
    handle,
)

__all__ = ["DataFilterConfig", "DataFilterInput", "DataFilterOutput"]

register(
    NodeDefinition(
        id="data.filter",
        version=1,
        name="Filter a list",
        category="data",
        description="Keep the items of a list for which a condition holds.",
        kind="action",
        config_schema=DataFilterConfig,
        input_schema=DataFilterInput,
        output_schema=DataFilterOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=DataFilterOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
