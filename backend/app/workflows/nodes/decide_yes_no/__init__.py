"""`decide.yes_no` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._decide import DecisionConfig, DecisionInput, check_key
from app.workflows.nodes.decide_yes_no._handler import YesNoOutput, handle, routes

__all__ = ["YesNoOutput"]

register(
    NodeDefinition(
        id="decide.yes_no",
        version=1,
        name="Yes or no",
        category="decide",
        description="Ask Jev a yes-or-no question about a text, and branch on the answer.",
        kind="control",
        config_schema=DecisionConfig,
        input_schema=DecisionInput,
        output_schema=YesNoOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="yes", label="Yes", kind="output", schema=YesNoOutput),
            Port(id="no", label="No", kind="output", schema=YesNoOutput),
            Port(id="unsure", label="Unsure", kind="output", schema=YesNoOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        resource_check=check_key,
    )
)
