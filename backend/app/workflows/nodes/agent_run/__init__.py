"""`agent.run` - registration and nothing else. See `_handler.py` and `README.md`."""

from app.workflows._registry import register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.nodes.agent_run._handler import (
    AgentRunConfig,
    AgentRunInput,
    AgentRunOutput,
    AgentVersionPin,
    check_resources,
    handle,
)

__all__ = ["AgentRunConfig", "AgentRunInput", "AgentRunOutput", "AgentVersionPin"]

register(
    NodeDefinition(
        id="agent.run",
        version=1,
        name="Run an agent",
        category="agent",
        description="Ask a published agent, at a pinned version, and use its answer.",
        kind="action",
        config_schema=AgentRunConfig,
        input_schema=AgentRunInput,
        output_schema=AgentRunOutput,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=AgentRunOutput),
        ),
        effect_kind="write",
        retry_guarantee="none",
        handler=handle,
        resource_check=check_resources,
    )
)
