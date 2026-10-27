"""`trigger.outlook` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import EmailTriggerOutput
from app.workflows.nodes.trigger_outlook._handler import OutlookTriggerConfig, handle
from app.workflows.triggers import OUTLOOK

register(
    NodeDefinition(
        id=OUTLOOK,
        version=1,
        name="Outlook",
        category=TRIGGER_CATEGORY,
        description=(
            "A new email arrives in a folder of the organization's connected Microsoft 365 mailbox."
        ),
        kind="action",
        config_schema=OutlookTriggerConfig,
        input_schema=None,
        output_schema=EmailTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=EmailTriggerOutput),),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
