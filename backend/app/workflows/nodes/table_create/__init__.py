"""`table.create` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_create._handler import (
    TableCreateConfig,
    TableCreatedOutput,
    check_resources,
    handle,
)

__all__ = ["TableCreateConfig", "TableCreatedOutput"]

register(
    NodeDefinition(
        id="table.create",
        version=1,
        name="Create a table",
        category="tables",
        description="Create a new Virtual Table with the given columns.",
        kind="action",
        config_schema=TableCreateConfig,
        input_schema=None,
        output_schema=TableCreatedOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TableCreatedOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        scopes=frozenset({"tables:read", "tables:write"}),
        handler=handle,
        resource_check=check_resources,
    )
)
