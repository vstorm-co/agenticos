"""`error.raise` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.error_raise._handler import ErrorRaiseConfig, handle

__all__ = ["ErrorRaiseConfig"]

register(
    NodeDefinition(
        id="error.raise",
        version=1,
        name="Raise error",
        category="error",
        description="Fail this branch with an error you define.",
        kind="action",
        config_schema=ErrorRaiseConfig,
        input_schema=None,
        output_schema=None,
        ports=(Port(id="in", label="In", kind="input", schema=None),),
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
    )
)
