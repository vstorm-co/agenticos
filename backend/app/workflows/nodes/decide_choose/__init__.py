"""`decide.choose` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes._decide import DecisionInput, check_key
from app.workflows.nodes.decide_choose._handler import (
    ChooseConfig,
    ChooseOutput,
    DecisionOption,
    handle,
    routes,
)

__all__ = ["ChooseConfig", "ChooseOutput", "DecisionOption"]

register(
    NodeDefinition(
        id="decide.choose",
        version=1,
        name="Choose one",
        category="decide",
        description="Ask Jev which of your options fits a text - a category, a queue, an intent.",
        kind="control",
        config_schema=ChooseConfig,
        input_schema=DecisionInput,
        output_schema=ChooseOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Chosen", kind="output", schema=ChooseOutput),
            Port(id="unsure", label="Unsure", kind="output", schema=ChooseOutput),
        ),
        effect_kind="read",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        resource_check=check_key,
    )
)
