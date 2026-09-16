"""Skills capability - an organization's reusable know-how."""

from app.agents.capabilities._registry import (
    LOAD_CAPABILITY,
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
    # The name comes from `pydantic-ai-skills` and is somebody else's to change;
    # the drift test is what tells us when they did. What the tool *returns* is
    # this repository's text - see `SKILL_TEXTS`. The skills themselves are not
    # tools: each is a deferred capability the model opens with
    # `load_capability`, so there is nothing here to gate or rename for them.
    tools=(
        *(
            # The summary each tool's text opens with, so the Builder shows the
            # sentence the model reads first rather than a fourth copy of it.
            CapabilityToolInfo(id=tool_id, description=text.summary)
            for tool_id, text in SKILL_TEXTS.items()
        ),
        # The framework's own, declared here because it is the tool that opens a
        # skill and therefore the only place an approval gate on skills can sit.
        # Pydantic AI provides it - nothing here builds or renames it - so it is
        # in `DECLARED_AND_NOT_OFFERED` in the drift test, and `ApprovalGate`
        # knows it by name rather than by capability id (#1704 review).
        CapabilityToolInfo(
            id=LOAD_CAPABILITY,
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
    return Skills(skills=skills)
