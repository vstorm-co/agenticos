"""Python control flow over workflow actions, without an orchestrating model."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.code_python_actions._handler import handle
from app.workflows.nodes.code_python_simple import PythonSimpleInput, PythonSimpleOutput
from app.workflows.python_actions import PythonActionsConfig, action_resource_problems

register(
    NodeDefinition(
        id="code.python.actions",
        version=1,
        name="Python with actions",
        category="code",
        description="Write Python that calls the workflow actions you bind by name.",
        kind="action",
        config_schema=PythonActionsConfig,
        input_schema=PythonSimpleInput,
        output_schema=PythonSimpleOutput,
        ports=(
            Port(id="in", label="In", kind="input"),
            Port(id="out", label="Out", kind="output", schema=PythonSimpleOutput),
        ),
        effect_kind="write",
        # The interpreter segment itself never performs I/O. Each action is a
        # separately claimed node run with the action's own retry guarantee.
        retry_guarantee="idempotent",
        scopes=frozenset({"code:execute"}),
        resource_check=action_resource_problems,
        handler=handle,
    )
)
