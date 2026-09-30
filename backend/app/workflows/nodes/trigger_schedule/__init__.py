"""`trigger.schedule` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import ScheduleTriggerConfig, ScheduleTriggerOutput
from app.workflows.nodes.trigger_schedule._handler import handle
from app.workflows.triggers import SCHEDULE

register(
    NodeDefinition(
        id=SCHEDULE,
        version=1,
        name="Schedule",
        category=TRIGGER_CATEGORY,
        description="Runs on a clock: every so often, or on a cron expression in UTC.",
        kind="action",
        config_schema=ScheduleTriggerConfig,
        input_schema=None,
        output_schema=ScheduleTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=ScheduleTriggerOutput),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
