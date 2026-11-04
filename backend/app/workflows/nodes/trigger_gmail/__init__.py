"""`trigger.gmail` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import EmailTriggerOutput
from app.workflows.nodes.trigger_gmail._handler import GmailTriggerConfig, handle
from app.workflows.triggers import GMAIL

register(
    NodeDefinition(
        id=GMAIL,
        version=1,
        name="Gmail",
        category=TRIGGER_CATEGORY,
        description="A new email arrives in the organization's connected Gmail mailbox.",
        kind="action",
        config_schema=GmailTriggerConfig,
        input_schema=None,
        output_schema=EmailTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=EmailTriggerOutput),),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
