"""`table.record.update` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._tables import TableRecordOutput
from app.workflows.nodes.table_record_update._handler import (
    TableRecordUpdateConfig,
    TableRecordUpdateInput,
    check_resources,
    handle,
)

__all__ = ["TableRecordUpdateConfig", "TableRecordUpdateInput"]

register(
    NodeDefinition(
        id="table.record.update",
        version=1,
        name="Update a record",
        category="tables",
        description="Change some of a record's cells.",
        kind="action",
        config_schema=TableRecordUpdateConfig,
        input_schema=TableRecordUpdateInput,
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
