"""Media capability - keep a compacted history's pictures out of the database."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.media._capability import MediaOffload, restore_stored_media
from app.agents.capabilities.media._store import (
    ORGANIZATION_RESOURCE,
    OrganizationMediaStore,
)

__all__ = [
    "ORGANIZATION_RESOURCE",
    "MediaConfig",
    "MediaOffload",
    "OrganizationMediaStore",
    "restore_stored_media",
]


class MediaConfig(BaseModel):
    """How large a part has to be before it is worth storing out of line."""

    threshold_bytes: int = Field(
        default=32_768,
        ge=1_024,
        le=10 * 1024 * 1024,
        description=(
            "Binary or text parts at least this large are written to storage and "
            "replaced with a reference in the stored history."
        ),
    )


@register(
    id="media",
    name="Media offload",
    category="utility",
    description=(
        "Store a compacted conversation's images out of line, so the history stays small."
    ),
    # No tools by design: this rewrites what is *stored*, not what the model can
    # do, so there is nothing here for a model to call or a person to approve.
    # See `media/_capability.py`.
    tools=(),
    config_schema=MediaConfig,
)
def _build(ctx: CapabilityBuildContext) -> MediaOffload[object]:
    """Build the offloader for this run's organization.

    Always returns something, the way `compaction` does: binding the capability
    *is* the decision to offload. The organization comes from `resources` rather
    than from configuration - whose store a run writes to is not a builder's to
    choose - and is absent in a preview, where the capability then offloads
    nothing rather than offloading somewhere shared.
    """
    config = ctx.config if isinstance(ctx.config, MediaConfig) else MediaConfig()
    organization_id = ctx.resources.get(ORGANIZATION_RESOURCE)
    return MediaOffload(
        organization_id=organization_id if isinstance(organization_id, UUID) else None,
        threshold_bytes=config.threshold_bytes,
    )
