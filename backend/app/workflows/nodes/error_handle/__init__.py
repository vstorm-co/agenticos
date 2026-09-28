"""`error.handle` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition
from app.workflows.nodes.error_handle._handler import (
    STATIC_PORTS,
    ErrorBranch,
    ErrorHandleConfig,
    HandledError,
    handle,
    ports_for,
    routes,
)

__all__ = ["ErrorBranch", "ErrorHandleConfig", "HandledError"]

register(
    NodeDefinition(
        id="error.handle",
        version=1,
        name="Handle error",
        category="error",
        description="Route a failure to a branch chosen by its error code.",
        kind="control",
        config_schema=ErrorHandleConfig,
        input_schema=None,
        output_schema=HandledError,
        ports=STATIC_PORTS,
        effect_kind="pure",
        retry_guarantee="idempotent",
        handler=handle,
        routes=routes,
        ports_for=ports_for,
    )
)
