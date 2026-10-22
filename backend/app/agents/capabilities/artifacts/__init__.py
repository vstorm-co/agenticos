"""Artifacts capability - publish a report or a small dashboard under a stable link."""

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
        description=(
            "Hand the model the picture of a page when it previews one. Turn off for a "
            "model that cannot read images; the written report still comes back."
        ),
    )


@register(
    id=ARTIFACTS_CAPABILITY_ID,
    name="Artifacts",
    category="utility",
    description=(
        "Let the agent publish a finished page - a report, a small dashboard, a one-page "
        "summary - under a link people open in a browser. Publishing again under the same "
        "name updates the page behind the same link and keeps the earlier versions, and the "
        "agent can list its pages, read one back to change part of it, preview one to "
        "see it as a reader would, and ask for one to be shared, which its owner approves. "
        "A new page is private to the person the run was for until they share it."
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
        CapabilityToolInfo(
            id="list_artifacts",
            description="List the pages this agent published that this run may open, newest first.",
        ),
        CapabilityToolInfo(
            id="preview_artifact",
            description=(
                "See a page you published as somebody opening it would: a picture, and what "
                "went wrong."
            ),
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

    config = ctx.config if isinstance(ctx.config, ArtifactsConfig) else ArtifactsConfig()
    return Artifacts(
        table_grants=ctx.resources.get(TABLE_GRANTS_RESOURCE, MappingProxyType({})),
        screenshot=config.preview_screenshot,
    )
