"""`code.javascript.sandbox` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.code_javascript_sandbox._handler import (
    JavaScriptSandboxConfig,
    JavaScriptSandboxInput,
    JavaScriptSandboxOutput,
    check_resources,
    handle,
)

__all__ = ["JavaScriptSandboxConfig", "JavaScriptSandboxInput", "JavaScriptSandboxOutput"]

register(
    NodeDefinition(
        id="code.javascript.sandbox",
        version=1,
        name="JavaScript in a sandbox",
        category="code",
        description=(
            "Run JavaScript on Node with the run's files as a durable job on the "
            "organization's sandbox host, with no platform credentials inside it."
        ),
        kind="action",
        config_schema=JavaScriptSandboxConfig,
        input_schema=JavaScriptSandboxInput,
        output_schema=JavaScriptSandboxOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=JavaScriptSandboxOutput),
        ),
        effect_kind="write",
        retry_guarantee="idempotent",
        scopes=frozenset({"sandbox:execute"}),
        handler=handle,
        resource_check=check_resources,
    )
)
