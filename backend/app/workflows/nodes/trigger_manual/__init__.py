"""`trigger.manual` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.nodes.trigger_manual._handler import (
    STATIC_PORTS,
    TriggerInputConfig,
    handle,
    ports_for,
)
from app.workflows.triggers import MANUAL

register(
    NodeDefinition(
        id=MANUAL,
        version=1,
        name="Manual",
        category=TRIGGER_CATEGORY,
        description="Start by clicking Run in the editor or on the workflow's runs page.",
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
