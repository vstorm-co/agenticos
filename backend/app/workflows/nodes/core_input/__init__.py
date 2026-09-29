"""`core.input` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.nodes.core_input._handler import (
    STATIC_PORTS,
    InputField,
    ManualTriggerConfig,
    handle,
    ports_for,
)
from app.workflows.triggers import MANUAL

__all__ = ["InputField", "ManualTriggerConfig"]

register(
    NodeDefinition(
        id=MANUAL,
        version=1,
        name="Manual or API",
        category=TRIGGER_CATEGORY,
        description="Start by hand, from the API or over a WebSocket, with the payload you give.",
        kind="action",
        config_schema=ManualTriggerConfig,
        input_schema=None,
        output_schema=WorkflowInputPayload,
        ports=STATIC_PORTS,
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        ports_for=ports_for,
    )
)
