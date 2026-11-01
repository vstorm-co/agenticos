"""`notification.send` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.notification_send._handler import (
    NotificationSendConfig,
    NotificationSendInput,
    NotificationSendOutput,
    check_resources,
    handle,
)

__all__ = ["NotificationSendConfig", "NotificationSendInput", "NotificationSendOutput"]

register(
    NodeDefinition(
        id="notification.send",
        version=1,
        name="Notify members",
        category="notification",
        description="Notify members of the organization in the app or by email.",
        kind="action",
        config_schema=NotificationSendConfig,
        input_schema=NotificationSendInput,
        output_schema=NotificationSendOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=NotificationSendOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        handler=handle,
        resource_check=check_resources,
    )
)
