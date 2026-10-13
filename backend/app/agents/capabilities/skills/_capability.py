"""Skills capability - progressive disclosure over stored know-how.

The agent sees only names and one-line descriptions until it decides one is
relevant, then loads the body. Twenty skills therefore cost almost nothing in
context, and the twenty-first does not push the conversation out.

That disclosure is the model's own, not a tool this platform writes. Each skill
is a *deferred capability*: its name and description sit in the capability
catalog, and `load_capability` - pydantic-ai's built-in - brings the instructions
in. So the two tools this capability used to publish for that, `list_skills` and
`load_skill`, are gone, and `read_skill_resource` is the one that remains.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_skills import Skill as ToolkitSkill
from pydantic_ai_skills import SkillResource as ToolkitResource
from pydantic_ai_skills import SkillsCapability

from app.agents.capabilities._tool_text import ToolText
from app.db.models.skill import Skill

# What this capability publishes as a tool. The catalog and the skill bodies are
# not here because they are not tools: the model reads the first in its own
# capability list and opens the second with `load_capability`.
#
# `run_skill_script` is absent by construction, not merely unused: without a
# sandbox it is remote code execution wearing a helpful name. A skill's scripts
# reach a run as files under `/workspace/skills/`, where the sandbox's own
# `execute` runs them under the operator's ceilings - see
# `app/services/skill_workspace.py` for why there is deliberately no second way.
SAFE_SKILL_TOOLS = ("read_skill_resource",)


def to_toolkit_skill(skill: Skill) -> ToolkitSkill:
    """Convert a stored skill into what the capability consumes."""
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


SKILL_TEXTS: dict[str, ToolText] = {
    "read_skill_resource": ToolText(
        summary="Access supplementary documentation, templates, or data from a skill.",
        usage=(
            "Resources are the files a skill ships beside its instructions: "
            "templates, schemas, reference documents. Read one when the skill's "
            "instructions point at it by name, which is where the names come "
            "from - a loaded skill lists its files under 'Bundled files', and "
            "a skill you have not opened with `load_capability` has none you "
            "can reach."
        ),
        returns=(
            "The resource's content as text. A skill or a resource name that "
            "does not exist comes back as an error rather than as empty content, "
            "so an empty answer means the file is genuinely empty."
        ),
    ),
}
"""What the model reads about the skills tool.

The library is a third party's (`pydantic-ai-skills`), and its own text is sound
but answers "what will I get" with one clause - the content, as a string - which
leaves the model with no way to tell a missing file from an empty one. That is
the question a model asks before calling, so this repository writes it. What the
tool is *for* stays the library's wording, because that part was already right.
"""


class Skills(SkillsCapability[AgentDepsT]):
    """Hands an agent a set of skills it can load on demand.

    Skills are passed in memory rather than written to a temporary directory -
    the library accepts `Skill` objects directly - which removes temp-file
    cleanup, a race between concurrent runs, and a path traversal surface.
    """

    def __init__(self, skills: list[Skill]) -> None:
        """Build the deferred catalog, and re-describe the tool it carries.

        A set of skills that ships no files carries no toolset at all - there is
        nothing for `read_skill_resource` to read - and is purely a catalog of
        deferred capabilities.

        Args:
            skills: The stored skills resolved for this run. Must not be empty;
                an agent with no skills gets no capability at all, which is what
                keeps an unusable tool out of the list the model reads each turn.
        """
        super().__init__(
            skills=[to_toolkit_skill(skill) for skill in skills],
            # No second way to run things. See `SAFE_SKILL_TOOLS`.
            scripts=False,
        )
        toolset = self.get_toolset()
        if isinstance(toolset, FunctionToolset):
            _describe(toolset)


def _describe(toolset: FunctionToolset[Any]) -> None:
    """Give the library's tools this deployment's text, in place.

    Only the tools `SKILL_TEXTS` has an answer for. The library adds what it
    adds, and a tool nobody here has written about keeps its own description
    rather than losing one - `run_skill_script` is switched off rather than
    described, and switching it back on must not leave it mute.

    `Tool.description` is what `get_tools` builds each `ToolDefinition` from, so
    setting it here reaches both the model and the Builder's contract reader.
    """
    for name, tool in toolset.tools.items():
        text = SKILL_TEXTS.get(name)
        if text is not None:
            tool.description = text.render()
