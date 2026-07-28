"""Skills capability — an organization's reusable know-how."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.skills._capability import (
    SAFE_SKILL_TOOLS,
    Skills,
    to_toolkit_skill,
)

__all__ = ["SAFE_SKILL_TOOLS", "Skills", "to_toolkit_skill"]


@register(
    id="skills",
    name="Skills",
    category="knowledge",
    description="Load the organization's written know-how on demand, one skill at a time.",
    # These three come from `pydantic-ai-skills`, so their names and wording are
    # somebody else's to change. The drift test is what tells us when they did.
    tools=(
        CapabilityToolInfo(
            id="list_skills",
            description="Get an overview of all available skills and what they do.",
        ),
        CapabilityToolInfo(
            id="load_skill",
            description="Load complete instructions and capabilities for a specific skill.",
        ),
        CapabilityToolInfo(
            id="read_skill_resource",
            description="Access supplementary documentation, templates, or data from a skill.",
        ),
    ),
    scopes=("knowledge:read",),
)
def _build(ctx: CapabilityBuildContext) -> Skills | None:
    """Build from the skills resolved for this run.

    The skills themselves are a field on the agent spec, resolved server-side —
    a capability never queries the database.
    """
    skills = ctx.resources.get("skills") or []
    if not skills:
        return None
    return Skills(skills=skills)
