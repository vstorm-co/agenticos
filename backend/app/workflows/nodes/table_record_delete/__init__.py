"""`table.record.delete` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_record_delete._handler import (
    TableRecordDeleteConfig,
    TableRecordDeleteInput,
    TableRecordDeleteOutput,
    check_resources,
    handle,
)

__all__ = ["TableRecordDeleteConfig", "TableRecordDeleteInput", "TableRecordDeleteOutput"]

register(
    NodeDefinition(
        id="table.record.delete",
        version=1,
        name="Delete a record",
        category="tables",
        description="Delete a record. Its history is kept.",
        kind="action",
        config_schema=TableRecordDeleteConfig,
        input_schema=TableRecordDeleteInput,
        output_schema=TableRecordDeleteOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TableRecordDeleteOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        scopes=frozenset({"tables:read", "tables:write"}),
        handler=handle,
        resource_check=check_resources,
    )
)
