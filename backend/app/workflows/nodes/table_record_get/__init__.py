"""`table.record.get` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_record_get._handler import (
    TableRecordGetConfig,
    TableRecordGetInput,
    TableRecordLookup,
    check_resources,
    handle,
)

__all__ = ["TableRecordGetConfig", "TableRecordGetInput", "TableRecordLookup"]

register(
    NodeDefinition(
        id="table.record.get",
        version=1,
        name="Find a record",
        category="tables",
        description="Read one record by its id or external id.",
        kind="action",
        config_schema=TableRecordGetConfig,
        input_schema=TableRecordGetInput,
        output_schema=TableRecordLookup,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TableRecordLookup),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        scopes=frozenset({"tables:read"}),
        handler=handle,
        resource_check=check_resources,
    )
)
