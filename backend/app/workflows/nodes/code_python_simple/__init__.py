"""`code.python.simple` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.code_python_simple._handler import (
    PythonSimpleConfig,
    PythonSimpleInput,
    PythonSimpleOutput,
    handle,
)

__all__ = ["PythonSimpleConfig", "PythonSimpleInput", "PythonSimpleOutput"]

register(
    NodeDefinition(
        id="code.python.simple",
        version=1,
        name="Python script",
        category="code",
        description=(
            "Compute a JSON value with a short Python script in the Monty sandbox - no "
            "files, no network, a small standard library."
        ),
        kind="action",
        config_schema=PythonSimpleConfig,
        input_schema=PythonSimpleInput,
        output_schema=PythonSimpleOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=PythonSimpleOutput),
        ),
        effect_kind="pure",
        retry_guarantee="idempotent",
        scopes=frozenset({"code:execute"}),
        handler=handle,
    )
)
