"""`logic.split` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition
from app.workflows.nodes.logic_split._handler import (
    STATIC_PORTS,
    LogicSplitConfig,
    LogicSplitOutput,
    SplitBranch,
    handle,
    ports_for,
)

__all__ = ["LogicSplitConfig", "LogicSplitOutput", "SplitBranch"]

register(
    NodeDefinition(
        id="logic.split",
        version=1,
        name="Split",
        category="logic",
        description="Send the run down several branches at once.",
        kind="control",
        config_schema=LogicSplitConfig,
        input_schema=None,
        output_schema=LogicSplitOutput,
        ports=STATIC_PORTS,
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        routes=None,
        exclusive_branches=False,
        ports_for=ports_for,
    )
)
