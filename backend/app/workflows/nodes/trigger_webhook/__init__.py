"""`trigger.webhook` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition, Port
from app.workflows.nodes._triggers import WebhookTriggerOutput
from app.workflows.nodes.trigger_webhook._handler import handle
from app.workflows.triggers import WEBHOOK

register(
    NodeDefinition(
        id=WEBHOOK,
        version=1,
        name="Webhook",
        category=TRIGGER_CATEGORY,
        description="A signed HTTP delivery arrives at this workflow's own address.",
        kind="action",
        config_schema=None,
        input_schema=None,
        output_schema=WebhookTriggerOutput,
        ports=(Port(id="out", label="Out", kind="output", schema=WebhookTriggerOutput),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
