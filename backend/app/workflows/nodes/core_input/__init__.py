"""`core.input` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.nodes.core_input._handler import (
    STATIC_PORTS,
    InputField,
    TriggerInputConfig,
    handle,
    ports_for,
)
from app.workflows.triggers import API

__all__ = ["InputField", "TriggerInputConfig"]

register(
    NodeDefinition(
        id=API,
        version=1,
        name="API request",
        category=TRIGGER_CATEGORY,
        description="Start from an HTTP request or over a WebSocket, with the input you declare.",
        kind="action",
        config_schema=TriggerInputConfig,
        input_schema=None,
        output_schema=WorkflowInputPayload,
        ports=STATIC_PORTS,
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        ports_for=ports_for,
    )
)
