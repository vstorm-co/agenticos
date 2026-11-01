"""`loop.yield` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.loop_yield._handler import LoopYieldInput, LoopYieldOutput, handle

__all__ = ["LoopYieldInput", "LoopYieldOutput"]

register(
    NodeDefinition(
        id="loop.yield",
        version=1,
        name="Loop result",
        category="control",
        description="End this iteration of a loop, handing back its result.",
        kind="control",
        config_schema=None,
        input_schema=LoopYieldInput,
        output_schema=LoopYieldOutput,
        ports=(Port(id="in", label="In", kind="input", schema=None),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        loop_body_only=True,
    )
)
