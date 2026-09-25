"""Artifacts capability - publish a report or a small dashboard under a stable link."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.artifacts._capability import Artifacts
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE

__all__ = ["ARTIFACTS_CAPABILITY_ID", "Artifacts"]

ARTIFACTS_CAPABILITY_ID = "artifacts"


@register(
    id=ARTIFACTS_CAPABILITY_ID,
    name="Artifacts",
    category="utility",
    description=(
        "Let the agent publish a finished page - a report, a small dashboard, a one-page "
        "summary - under a link people open in a browser. Publishing again under the same "
        "name updates the page behind the same link and keeps the earlier versions. A new "
        "page is private to the person the run was for until they share it."
    ),
    tools=(
        CapabilityToolInfo(
            id="publish_artifact",
            description=(
                "Publish a finished page - a report, a small dashboard, a summary - under a "
                "stable link."
            ),
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> Artifacts:
    """Never `None`: an agent without a workspace still publishes content it passes inline."""
    return Artifacts(workspace_backend=ctx.resources.get(WORKSPACE_BACKEND_RESOURCE))
