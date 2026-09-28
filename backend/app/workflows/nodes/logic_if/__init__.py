"""`logic.if` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.logic_if._handler import (
    LogicIfConfig,
    LogicIfInput,
    LogicIfOutput,
    handle,
    routes,
)

__all__ = ["LogicIfConfig", "LogicIfInput", "LogicIfOutput"]

register(
    NodeDefinition(
        id="logic.if",
        version=1,
        name="If / else",
        category="logic",
        description="Continue down one of two branches, decided by a condition.",
        kind="control",
        config_schema=LogicIfConfig,
        input_schema=LogicIfInput,
        output_schema=LogicIfOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="true", label="True", kind="output", schema=LogicIfOutput),
            Port(id="false", label="False", kind="output", schema=LogicIfOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
    )
)
