"""Workflows capability - start the workflows an agent is given, as tools."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.workflows._capability import Workflows, WorkflowsConfig

__all__ = ["Workflows", "WorkflowsConfig"]


@register(
    id="workflows",
    name="Workflows",
    category="automation",
    description="Start published workflows as tools, and read what they answered.",
    tools=(
        CapabilityToolInfo(
            id="list_workflows",
            description="List the workflows this agent may start, with what each needs as input.",
            side_effecting=False,
        ),
        CapabilityToolInfo(
            id="run_workflow",
            description="Start one of this agent's workflows, and wait for what it answers.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="get_workflow_run",
            description="Read how a workflow run this agent started stands now.",
            side_effecting=False,
        ),
    ),
    config_schema=WorkflowsConfig,
    scopes=("workflows:run",),
)
def _build(ctx: CapabilityBuildContext) -> Workflows | None:
    """Build the capability, or nothing when it names no workflow - tools that can only
    refuse are worse than none, since the model keeps trying them."""
    config = ctx.config if isinstance(ctx.config, WorkflowsConfig) else WorkflowsConfig()
    if not config.workflow_ids:
        return None
    return Workflows(workflow_ids=tuple(config.workflow_ids), wait_seconds=config.wait_seconds)
