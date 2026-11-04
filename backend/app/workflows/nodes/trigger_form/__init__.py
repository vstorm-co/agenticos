"""`trigger.form` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import TRIGGER_CATEGORY, NodeDefinition
from app.workflows.contracts.io import WorkflowInputPayload
from app.workflows.nodes.trigger_form._handler import (
    STATIC_PORTS,
    FormTriggerConfig,
    handle,
    ports_for,
)
from app.workflows.triggers import FORM

register(
    NodeDefinition(
        id=FORM,
        version=1,
        name="Form",
        category=TRIGGER_CATEGORY,
        description="Somebody fills in a form at the workflow's public address.",
        kind="action",
        config_schema=FormTriggerConfig,
        input_schema=None,
        output_schema=WorkflowInputPayload,
        ports=STATIC_PORTS,
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        ports_for=ports_for,
    )
)
