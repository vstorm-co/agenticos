"""Explicit background topics, separate from a run's temporary async tools."""

from uuid import UUID

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.background_tasks._capability import BackgroundTasks
from app.agents.capabilities.background_tasks._toolset import (
    LIST_DESCRIPTION,
    START_DESCRIPTION,
    STOP_DESCRIPTION,
)
from app.schemas.local_target import LocalTarget

__all__ = ["BackgroundTasks"]


@register(
    id="background_tasks",
    name="Background topics",
    category="reasoning",
    description="Start a fresh topic with this agent or a pinned delegate, keep talking here, and receive its result when it finishes.",
    tools=(
        CapabilityToolInfo(
            id="start_background_task", description=START_DESCRIPTION, side_effecting=True
        ),
        CapabilityToolInfo(
            id="list_background_tasks", description=LIST_DESCRIPTION, side_effecting=False
        ),
        CapabilityToolInfo(
            id="stop_background_task", description=STOP_DESCRIPTION, side_effecting=True
        ),
    ),
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> BackgroundTasks:
    local = ctx.resources.get("background_tasks.local")
    profile = ctx.resources.get("background_tasks.model_profile_id")
    return BackgroundTasks(
        local=local if isinstance(local, LocalTarget) else None,
        model_profile_id=profile if isinstance(profile, UUID) else None,
    )
