"""`table.record.query` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_record_query._handler import (
    TableRecordPage,
    TableRecordQueryConfig,
    check_resources,
    handle,
)

__all__ = ["TableRecordPage", "TableRecordQueryConfig"]

register(
    NodeDefinition(
        id="table.record.query",
        version=1,
        name="List records",
        category="tables",
        description="List a table's records, filtered and sorted.",
        kind="action",
        config_schema=TableRecordQueryConfig,
        input_schema=None,
        output_schema=TableRecordPage,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TableRecordPage),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        scopes=frozenset({"tables:read"}),
        handler=handle,
        resource_check=check_resources,
    )
)
