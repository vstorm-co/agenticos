"""`table.describe` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_describe._handler import (
    TableDescribeConfig,
    TableDescribeOutput,
    check_resources,
    handle,
)

register(
    NodeDefinition(
        id="table.describe",
        version=1,
        name="Describe a table",
        category="tables",
        description="Read a table's name and its live columns for the steps after it.",
        kind="action",
        config_schema=TableDescribeConfig,
        input_schema=None,
        output_schema=TableDescribeOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TableDescribeOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
    )
)
