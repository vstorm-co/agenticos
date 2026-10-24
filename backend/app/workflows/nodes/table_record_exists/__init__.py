"""`table.record.exists` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.table_record_exists._handler import (
    TableRecordExistsConfig,
    TableRecordExistsOutput,
    check_resources,
    handle,
    routes,
)

register(
    NodeDefinition(
        id="table.record.exists",
        version=1,
        name="Record exists?",
        category="tables",
        description="Branch on whether any record of a table matches your filters.",
        kind="control",
        config_schema=TableRecordExistsConfig,
        input_schema=None,
        output_schema=TableRecordExistsOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="yes", label="Yes", kind="output", schema=TableRecordExistsOutput),
            Port(id="no", label="No", kind="output", schema=TableRecordExistsOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        resource_check=check_resources,
    )
)
