"""`code.python.sandbox` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.code_python_sandbox._handler import (
    PythonSandboxConfig,
    PythonSandboxInput,
    PythonSandboxOutput,
    check_resources,
    handle,
)

__all__ = ["PythonSandboxConfig", "PythonSandboxInput", "PythonSandboxOutput"]

register(
    NodeDefinition(
        id="code.python.sandbox",
        version=1,
        name="Python in a sandbox",
        category="code",
        description=(
            "Run full Python with the run's files as a durable job on the organization's "
            "sandbox host, with no platform credentials inside it."
        ),
        kind="action",
        config_schema=PythonSandboxConfig,
        input_schema=PythonSandboxInput,
        output_schema=PythonSandboxOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=PythonSandboxOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        scopes=frozenset({"sandbox:execute"}),
        handler=handle,
        resource_check=check_resources,
    )
)
