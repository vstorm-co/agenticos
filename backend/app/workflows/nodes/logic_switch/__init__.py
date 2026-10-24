"""`logic.switch` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition
from app.workflows.nodes.logic_switch._handler import (
    STATIC_PORTS,
    LogicSwitchConfig,
    LogicSwitchInput,
    LogicSwitchOutput,
    SwitchRule,
    handle,
    ports_for,
    routes,
)

__all__ = ["LogicSwitchConfig", "LogicSwitchInput", "LogicSwitchOutput", "SwitchRule"]

register(
    NodeDefinition(
        id="logic.switch",
        version=1,
        name="Switch",
        category="logic",
        description="Continue down the first of many branches whose rule holds.",
        kind="control",
        config_schema=LogicSwitchConfig,
        input_schema=LogicSwitchInput,
        output_schema=LogicSwitchOutput,
        ports=STATIC_PORTS,
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        ports_for=ports_for,
    )
)
