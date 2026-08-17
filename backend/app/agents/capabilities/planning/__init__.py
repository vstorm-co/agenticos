"""Planning - a checklist the agent keeps for itself while it works.

For multi-step work a model does better when it writes the steps down first and
keeps them in front of itself: what is done, what is in progress, what is left. This
capability gives it the tools to do that and surfaces the current checklist back to
it every turn, as a cache-safe reminder that never invalidates the prompt cache.

It overlaps with delegation (`subagents`) the way a plan overlaps with a team:
planning decides *what* the steps are, delegation decides *who* does them. They are
orthogonal - a plan is a toolset plus a tail reminder, delegation is a toolset plus a
run wrapper, and neither restructures the other - so an agent may bind both, one, or
neither.

The checklist is state, and it survives an approval park: the runner owns the store,
seeds it from `paused_state` on resume, and reads it back when the run stops. See
`planning/_capability.py` for why the store lives there rather than here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai_harness.planning import Planning

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.planning._capability import (
    PLANNING_STORE_RESOURCE,
    PLANNING_TOOLS,
    build_planning,
    dump_plan,
    new_plan_store,
    open_plan_store,
)

__all__ = [
    "PLANNING_STORE_RESOURCE",
    "PLANNING_TOOLS",
    "PlanningConfig",
    "build_planning",
    "dump_plan",
    "new_plan_store",
    "open_plan_store",
]


class PlanningConfig(BaseModel):
    """How this agent plans.

    Both fields have defaults that make the smallest useful surface: a flat checklist
    with a short-lived cache breakpoint. An agent that binds the capability and sets
    nothing gets exactly that.
    """

    enable_subtasks: bool = Field(
        default=False,
        description=(
            "Add dependency-aware planning: three more tools (`add_subtask`, "
            "`set_dependency`, `get_available_tasks`) and a `blocked` status. A step "
            "with an unresolved prerequisite is held `blocked` until the prerequisite "
            "completes or is cancelled, and the agent asks which steps are free to "
            "start. Off by default: a flat checklist is the smaller prompt, and most "
            "work does not need a dependency graph to track it."
        ),
    )
    cache_ttl: Literal["5m", "1h"] = Field(
        default="5m",
        description=(
            "How long the provider may cache the prompt prefix that sits before the "
            "plan reminder. The reminder changes every turn and is deliberately kept "
            "behind this breakpoint so the stable prefix stays cacheable; a longer TTL "
            "suits a conversation that stays open, the shorter one a burst of turns."
        ),
    )


@register(
    id="planning",
    name="Planning",
    category="reasoning",
    description="Let the agent keep a checklist of steps for a multi-step task.",
    # All nine, including the three a flat checklist does not offer. A tool absent
    # from this list can be neither gated by the approval policy nor renamed by a
    # binding, and the offered subset is decided by `enable_subtasks` at build time.
    tools=PLANNING_TOOLS,
    config_schema=PlanningConfig,
    # None of the tools acts on the world - they mutate a checklist the model keeps
    # for itself - so there is nothing here for a person to approve.
    side_effecting=False,
)
def _build(ctx: CapabilityBuildContext) -> Planning:
    """Attach the planning tools, over the store the runner injected.

    Always attaches when bound: even the default configuration contributes the six
    core tools, so unlike `knowledge` or `subagents` there is no configuration that
    makes it contribute nothing. An agent that wants to contribute nothing does not
    bind it - and then it pays nothing, which is the invariant its test pins.

    The store arrives through `resources`, seeded from `paused_state` on a resume and
    empty on a fresh run. Absent - a preview or a unit test with no runner behind it -
    the library keeps its own fresh in-memory plan for the build.
    """
    config = ctx.config if isinstance(ctx.config, PlanningConfig) else PlanningConfig()
    return build_planning(
        enable_subtasks=config.enable_subtasks,
        cache_ttl=config.cache_ttl,
        store=ctx.resources.get(PLANNING_STORE_RESOURCE),
    )
