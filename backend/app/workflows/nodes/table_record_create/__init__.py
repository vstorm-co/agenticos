"""`table.record.create` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._tables import TableRecordOutput
from app.workflows.nodes.table_record_create._handler import (
    TableRecordCreateConfig,
    TableRecordCreateInput,
    check_resources,
    handle,
)

__all__ = ["TableRecordCreateConfig", "TableRecordCreateInput"]

register(
    NodeDefinition(
        id="table.record.create",
        version=1,
        name="Add a record",
        category="tables",
        description="Add a record to a Virtual Table.",
        kind="action",
        config_schema=TableRecordCreateConfig,
        input_schema=TableRecordCreateInput,
        output_schema=TableRecordOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TableRecordOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        scopes=frozenset({"tables:read", "tables:write"}),
        handler=handle,
        resource_check=check_resources,
    )
)
