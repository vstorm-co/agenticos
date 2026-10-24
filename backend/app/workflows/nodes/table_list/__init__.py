"""`table.list` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_list._handler import (
    TableListConfig,
    TableListInput,
    TableListOutput,
    handle,
)

register(
    NodeDefinition(
        id="table.list",
        version=1,
        name="List tables",
        category="tables",
        description="List the tables this run may see, found by part of a name.",
        kind="action",
        config_schema=TableListConfig,
        input_schema=TableListInput,
        output_schema=TableListOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TableListOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
