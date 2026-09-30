"""`trigger.table_record` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import TableRecordTriggerConfig, TableRecordTriggerOutput
from app.workflows.nodes.trigger_table_record._handler import check_resources, handle
from app.workflows.triggers import TABLE_RECORD

register(
    NodeDefinition(
        id=TABLE_RECORD,
        version=1,
        name="New table record",
        category=TRIGGER_CATEGORY,
        description="A record is added to a table, from anywhere, and matches the filters.",
        kind="action",
        config_schema=TableRecordTriggerConfig,
        input_schema=None,
        output_schema=TableRecordTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=TableRecordTriggerOutput),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
    )
)
