"""Skills capability - an organization's reusable know-how."""

from app.agents.capabilities._registry import (
    LOAD_CAPABILITY,
    READ_SKILL,
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.skills._capability import (
    SAFE_SKILL_TOOLS,
    SKILL_BODIES_RESOURCE,
    SKILL_TEXTS,
    SkillBody,
    SkillBodyFile,
    Skills,
    served_files,
    to_toolkit_skill,
)
from app.agents.capabilities.skills._log import (
    SKILL_USE_LOG_RESOURCE,
    ServedSkill,
    SkillUseLog,
    served_skills,
    tool_identities,
)

__all__ = [
    "SAFE_SKILL_TOOLS",
    "SKILL_BODIES_RESOURCE",
    "SKILL_USE_LOG_RESOURCE",
    "ServedSkill",
    "SkillBody",
    "SkillBodyFile",
    "SkillUseLog",
    "Skills",
    "served_files",
    "served_skills",
    "to_toolkit_skill",
    "tool_identities",
]


@register(
    id="skills",
    read_only=True,
    name="Skills",
    category="knowledge",
    description="Load the organization's written know-how on demand, one skill at a time.",
    # The file tool belongs to the skills library; the loader is the native
    # framework protocol with this platform's skill-specific presentation.
    tools=(
        *(
            # The summary each tool's text opens with, so the Builder shows the
            # sentence the model reads first rather than a fourth copy of it.
            CapabilityToolInfo(id=tool_id, description=text.summary)
            for tool_id, text in SKILL_TEXTS.items()
        ),
        # Keep the stable policy id so existing published approvals survive.
        # SkillLoader owns the model-facing name, outside ordinary overrides.
        CapabilityToolInfo(
            id=LOAD_CAPABILITY,
            name=READ_SKILL,
            description="Open a skill and read its instructions.",
            side_effecting=False,
        ),
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
    return Skills(
        skills=skills,
        bodies=ctx.resources.get(SKILL_BODIES_RESOURCE),
        log=ctx.resources.get(SKILL_USE_LOG_RESOURCE),
    )
