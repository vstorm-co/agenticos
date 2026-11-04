"""`text.compare` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.text_compare._handler import (
    TextCompareConfig,
    TextCompareInput,
    TextCompareOutput,
    handle,
)

__all__ = ["TextCompareConfig", "TextCompareInput", "TextCompareOutput"]

register(
    NodeDefinition(
        id="text.compare",
        version=1,
        name="Compare texts",
        category="data",
        description=(
            "Score how alike two texts are - 1 the same, 0 nothing in common - without a model."
        ),
        kind="action",
        config_schema=TextCompareConfig,
        input_schema=TextCompareInput,
        output_schema=TextCompareOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=TextCompareOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
