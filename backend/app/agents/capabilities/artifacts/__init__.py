"""Apps capability - publish a report or a small dashboard under a stable link.

Called artifacts until #2071; the id, the tool names and the tables keep that name.
"""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.artifacts._capability import Artifacts

__all__ = ["ARTIFACTS_CAPABILITY_ID", "Artifacts"]

ARTIFACTS_CAPABILITY_ID = "artifacts"


@register(
    id=ARTIFACTS_CAPABILITY_ID,
    name="Apps",
    category="utility",
    description=(
        "Let the agent publish a finished app - a report, a small dashboard, a one-page "
        "summary - under a link people open in a browser. Publishing again under the same "
        "name updates the app behind the same link and keeps the earlier versions, and the "
        "agent can read an app back to change part of it. A new app is private to the "
        "person the run was for until they share it."
    ),
    tools=(
        CapabilityToolInfo(
            id="publish_artifact",
            description=(
                "Publish a finished page - a report, a small dashboard, a summary - under a "
                "stable link."
            ),
        ),
        CapabilityToolInfo(
            id="read_artifact",
            description=(
                "Read the current version of a page this agent published, as it was written."
            ),
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> Artifacts:
    """Never `None`: an agent without a workspace still publishes content it passes inline."""
    return Artifacts()
