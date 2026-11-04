"""`webhook.respond` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.webhook_respond._handler import (
    WebhookRespondConfig,
    WebhookRespondInput,
    WebhookResponse,
    handle,
)
from app.workflows.triggers import WEBHOOK_RESPOND

__all__ = ["WebhookRespondConfig", "WebhookRespondInput", "WebhookResponse"]

register(
    NodeDefinition(
        id=WEBHOOK_RESPOND,
        version=1,
        name="Respond to webhook",
        category="core",
        description="Answer the webhook call that started the run: a status, headers and a body.",
        kind="action",
        config_schema=WebhookRespondConfig,
        input_schema=WebhookRespondInput,
        output_schema=WebhookResponse,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=WebhookResponse),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
