"""`loop.item` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.loop_item._handler import LoopItemOutput

__all__ = ["LoopItemOutput"]

register(
    NodeDefinition(
        id="loop.item",
        version=1,
        name="Loop item",
        category="control",
        description="The element this iteration of a loop works on.",
        kind="control",
        config_schema=None,
        input_schema=None,
        output_schema=LoopItemOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=LoopItemOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        loop_body_only=True,
    )
)
