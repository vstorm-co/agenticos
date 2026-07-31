"""Skills capability - progressive disclosure over stored know-how.

The agent sees only names and one-line descriptions until it decides one is
relevant, then loads the body. Twenty skills therefore cost almost nothing in
context, and the twenty-first does not push the conversation out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai_skills import Skill as ToolkitSkill
from pydantic_ai_skills import SkillResource as ToolkitResource
from pydantic_ai_skills import SkillsToolset

from app.db.models.skill import Skill

# What the toolset exposes. `run_skill_script` is absent by construction, not
# merely unused: without a sandbox it is remote code execution wearing a
# helpful name.
SAFE_SKILL_TOOLS = ("list_skills", "load_skill", "read_skill_resource")


def to_toolkit_skill(skill: Skill) -> ToolkitSkill:
    """Convert a stored skill into what the toolset consumes."""
    return ToolkitSkill(
        name=skill.name,
        description=skill.description,
        content=skill.content,
        resources=[
            ToolkitResource(
                name=resource.name,
                description=resource.description,
                content=resource.content,
            )
            for resource in skill.resources
        ],
    )


@dataclass
class Skills(AbstractCapability[AgentDepsT]):
    """Hands an agent a set of skills it can load on demand.

    Skills are passed in memory rather than written to a temporary directory -
    the toolset accepts objects directly - which removes temp-file cleanup, a
    race between concurrent runs, and a path traversal surface.
    """

    skills: list[Skill] = field(default_factory=list)

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        """The skills toolset, or nothing when the agent has no skills.

        Returning `None` keeps three unusable tools out of an agent that has
        no skills - every tool in the list is context the model reads each turn.
        """
        if not self.skills:
            return None
        if self._toolset is None:
            self._toolset = SkillsToolset(
                skills=[to_toolkit_skill(skill) for skill in self.skills],
                exclude_tools={"run_skill_script"},
            )
        return self._toolset
