"""Skills capability - an organization's reusable know-how."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.skills._capability import (
    SAFE_SKILL_TOOLS,
    SKILL_TEXTS,
    Skills,
    to_toolkit_skill,
)

__all__ = ["SAFE_SKILL_TOOLS", "Skills", "to_toolkit_skill"]


@register(
    id="skills",
    name="Skills",
    category="knowledge",
    description="Load the organization's written know-how on demand, one skill at a time.",
    # The three names come from `pydantic-ai-skills` and are somebody else's to
    # change; the drift test is what tells us when they did. What each tool
    # *returns* is this repository's text - see `SKILL_TEXTS`.
    tools=tuple(
        # The summary each tool's text opens with, so the Builder shows the
        # sentence the model reads first rather than a fourth copy of it.
        CapabilityToolInfo(id=tool_id, description=text.summary)
        for tool_id, text in SKILL_TEXTS.items()
    ),
    scopes=("knowledge:read",),
)
def _build(ctx: CapabilityBuildContext) -> Skills | None:
    """Build from the skills resolved for this run.

    The skills themselves are a field on the agent spec, resolved server-side -
    a capability never queries the database.
    """
    skills = ctx.resources.get("skills") or []
    if not skills:
        return None
    return Skills(skills=skills)
