"""`table.record.upsert` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._tables import TableRecordOutput
from app.workflows.nodes.table_record_upsert._handler import (
    TableRecordUpsertConfig,
    TableRecordUpsertInput,
    check_resources,
    handle,
)

__all__ = ["TableRecordUpsertConfig", "TableRecordUpsertInput"]

register(
    NodeDefinition(
        id="table.record.upsert",
        version=1,
        name="Save a record",
        category="tables",
        description="Create or update the record with an external id.",
        kind="action",
        config_schema=TableRecordUpsertConfig,
        input_schema=TableRecordUpsertInput,
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
