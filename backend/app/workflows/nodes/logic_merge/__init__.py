"""`logic.merge` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.logic_merge._handler import LogicMergeOutput, handle

__all__ = ["LogicMergeOutput"]

register(
    NodeDefinition(
        id="logic.merge",
        version=1,
        name="Merge",
        category="logic",
        description="Rejoin the two branches of an if / else into one path.",
        kind="control",
        config_schema=None,
        input_schema=None,
        output_schema=LogicMergeOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=LogicMergeOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
