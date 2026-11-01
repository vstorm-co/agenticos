"""`email.send` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.email_send._handler import (
    EmailSendConfig,
    EmailSendInput,
    EmailSendOutput,
    check_resources,
    handle,
)

__all__ = ["EmailSendConfig", "EmailSendInput", "EmailSendOutput"]

register(
    NodeDefinition(
        id="email.send",
        version=1,
        name="Send an email",
        category="email",
        description="Email up to ten addresses through an SMTP account or the platform sender.",
        kind="action",
        config_schema=EmailSendConfig,
        input_schema=EmailSendInput,
        output_schema=EmailSendOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=EmailSendOutput),
        ),
        effect_kind="write",
        retry_guarantee="at_least_once",
        handler=handle,
        resource_check=check_resources,
    )
)
