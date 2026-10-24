"""`table.exists` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_exists._handler import (
    TableExistsInput,
    TableExistsOutput,
    handle,
    routes,
)

register(
    NodeDefinition(
        id="table.exists",
        version=1,
        name="Table exists?",
        category="tables",
        description="Branch on whether a table of this name exists.",
        kind="control",
        config_schema=None,
        input_schema=TableExistsInput,
        output_schema=TableExistsOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="yes", label="Yes", kind="output", schema=TableExistsOutput),
            Port(id="no", label="No", kind="output", schema=TableExistsOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
    )
)
