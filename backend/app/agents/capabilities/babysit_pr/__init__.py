"""Babysit PR capability — watch a pull request through CI and review bots."""

from pydantic import BaseModel, Field

from app.agents.babysit_pr import (
    DEFAULT_MAX_WATCH_MINUTES,
    DEFAULT_POLL_SECONDS,
    MAX_POLL_SECONDS,
    MIN_POLL_SECONDS,
)
from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.babysit_pr._capability import (
    BABYSIT_PR_RECORDER_RESOURCE,
    BabysitPr,
)
from app.agents.manifest import RunRecorder

__all__ = [
    "BABYSIT_PR_RECORDER_RESOURCE",
    "BabysitPr",
    "BabysitPrConfig",
]


class BabysitPrConfig(BaseModel):
    """How babysit-pr watches: how often it polls, and for how long."""

    poll_interval_seconds: int = Field(
        title="Poll interval",
        default=DEFAULT_POLL_SECONDS,
        ge=MIN_POLL_SECONDS,
        le=MAX_POLL_SECONDS,
        description=(
            "Seconds between checks of the pull request. At least 60, "
            "so the watcher never polls in a tight loop and never burns "
            "the shared GitHub rate limit."
        ),
    )
    max_watch_minutes: int = Field(
        title="Watch at most",
        default=DEFAULT_MAX_WATCH_MINUTES,
        ge=30,
        le=1440,
        description=(
            "Minutes one watch may run before it stops and reports "
            "blocked. A watch that runs past this without green has "
            "not been approved — it has expired."
        ),
    )


@register(
    id="babysit_pr",
    name="Babysit PR",
    category="analysis",
    description=(
        "Watch a pull request through CI and review bots, reporting "
        "only what changed, and stop when the bots are green on the "
        "latest commit. Watching and reporting only — it never merges, "
        "comments, or takes any other action on the PR."
    ),
    tools=(
        CapabilityToolInfo(
            id="babysit_pr_check",
            description="Classify one snapshot of a pull request's checks.",
            read_only=True,
        ),
        CapabilityToolInfo(
            id="babysit_pr_rate_limit",
            description="Decide whether to watch again, from `gh api rate_limit`.",
            read_only=True,
        ),
        CapabilityToolInfo(
            id="babysit_pr_stop",
            description="Stop watching the pull request.",
        ),
    ),
    config_schema=BabysitPrConfig,
    side_effecting=False,
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> BabysitPr:
    """Build babysit-pr from its validated config and the run's recorder."""
    config = ctx.config if isinstance(ctx.config, BabysitPrConfig) else BabysitPrConfig()
    recorder = ctx.resources.get(BABYSIT_PR_RECORDER_RESOURCE)
    return BabysitPr(
        recorder=recorder if isinstance(recorder, RunRecorder) else RunRecorder(),
        poll_interval_seconds=config.poll_interval_seconds,
        max_watch_minutes=config.max_watch_minutes,
    )
