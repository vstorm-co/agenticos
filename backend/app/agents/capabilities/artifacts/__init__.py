"""Apps capability - publish a report or a small dashboard under a stable link.

Called artifacts until #2071; the id, the tool names and the tables keep that name.
"""

from types import MappingProxyType

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.artifacts._capability import Artifacts

__all__ = ["ARTIFACTS_CAPABILITY_ID", "Artifacts", "ArtifactsConfig"]

ARTIFACTS_CAPABILITY_ID = "artifacts"


class ArtifactsConfig(BaseModel):
    """How this agent's pages come back to it."""

    preview_screenshot: bool = Field(
        default=True,
        title="Show the model a page's picture",
        description=(
            "Hand the model the picture of a page when it previews one. Turn off for a "
            "model that cannot read images; the written report still comes back."
        ),
    )


@register(
    id=ARTIFACTS_CAPABILITY_ID,
    name="Apps",
    category="utility",
    description=(
        "Let the agent publish a finished app - a report, a small dashboard, a one-page "
        "summary - under a link people open in a browser. Publishing again under the same "
        "name updates the app behind the same link and keeps the earlier versions, and the "
        "agent can list its apps, read one back to change part of it, preview one to "
        "see it as a reader would, and ask for one to be shared, which its owner approves. "
        "A new app is private to the person the run was for until they share it."
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
                "Read a published app's source across conversations and sandboxes before updating it."
            ),
            read_only=True,
        ),
        CapabilityToolInfo(
            id="list_artifacts",
            description="List the pages this agent published that this run may open, newest first.",
            read_only=True,
        ),
        CapabilityToolInfo(
            id="preview_artifact",
            description=(
                "See a page you published as somebody opening it would: a picture, and what "
                "went wrong."
            ),
            read_only=True,
        ),
        CapabilityToolInfo(
            id="share_artifact",
            description=(
                "Ask for a page you published to be shared with more people; this shares "
                "nothing itself."
            ),
            side_effecting=False,
        ),
    ),
    config_schema=ArtifactsConfig,
)
def _build(ctx: CapabilityBuildContext) -> Artifacts:
    """Never `None`: an agent without a workspace still publishes content it passes inline."""
    # Function-local: `virtual_tables/_toolset.py` imports `app.services.virtual_tables` at
    # module level, which loops back through the factory to this package.
    from app.agents.capabilities.virtual_tables import TABLE_GRANTS_RESOURCE
    from app.agents.capabilities.workflows import WORKFLOW_IDS_RESOURCE

    config = ctx.config if isinstance(ctx.config, ArtifactsConfig) else ArtifactsConfig()
    return Artifacts(
        table_grants=ctx.resources.get(TABLE_GRANTS_RESOURCE, MappingProxyType({})),
        workflow_ids=ctx.resources.get(WORKFLOW_IDS_RESOURCE, frozenset()),
        screenshot=config.preview_screenshot,
    )
