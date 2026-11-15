"""Which skills a run used, kept for the run's terminal write."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.agents.capabilities._registry import LOAD_CAPABILITY, READ_SKILL, REGISTRY, load_builtins
from app.db.models.skill import Skill
from app.schemas.skill_usage import SkillUseRecord

if TYPE_CHECKING:
    from app.agents.capabilities.skills._capability import SkillBody
    from app.agents.spec import CapabilityBindingSpec

SKILL_USE_LOG_RESOURCE = "skill_use_log"

LOAD_TOOLS = frozenset({READ_SKILL, LOAD_CAPABILITY})
"""A model opens a skill with `read_skill`; histories from before it still say `load_capability`."""
RESOURCE_TOOL = "read_skill_resource"
LISTING_TOOL = "ls"
"""Listing a skill's folder names it without reading it, so it is not counted."""


@dataclass(frozen=True)
class ServedSkill:
    """A skill as one run was served it.

    Attributes:
        skill_id: The stored skill.
        version_id: The version the run was served, where one is known.
        projected: The body is a proposed one served in place of the stored skill.
    """

    skill_id: UUID
    version_id: UUID | None = None
    projected: bool = False


@dataclass
class _Tally:
    served: ServedSkill
    loaded: bool = False
    resource_reads: int = 0
    workspace_reads: int = 0


@dataclass
class SkillUseLog:
    """The skills one run used, by the agent that used them.

    Filled by the skills capability as tool calls finish and written by the runner
    when the run ends, so recording never touches the run's database session. A
    delegate gets a view of the same tallies under its own agent and skills
    through :meth:`for_agent`.

    Attributes:
        agent_id: The agent the uses are attributed to.
        served: The agent's skills by the name the model calls them.
        tools: The agent's tools by the name the model calls them, to their stable
            ids - what a binding's rename leaves alone. Empty reads every name as its id.
        tallies: What has been used so far, shared by every view.
        own: The view is the agent's own, not an inline specialist's. One record is
            kept per agent and skill, so where the two are served different versions
            of a skill, the agent's own version is the one recorded.
    """

    agent_id: UUID
    served: Mapping[str, ServedSkill]
    tools: Mapping[str, str] = field(default_factory=dict)
    tallies: dict[tuple[UUID, UUID], _Tally] = field(default_factory=dict)
    own: bool = True
    _paths: dict[str, re.Pattern[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # The workspace's skills folder, absolute or relative, or the older `/skills`;
        # never a deeper path that merely contains `skills/<name>`.
        self._paths = {
            name: re.compile(
                rf"(?<![\w./~-])(?:/workspace/|/|\./)?skills/{re.escape(name)}(?=/|$|[\s'\";|&)])"
            )
            for name in self.served
        }

    def for_agent(
        self,
        agent_id: UUID | None,
        served: Mapping[str, ServedSkill],
        tools: Mapping[str, str],
    ) -> SkillUseLog:
        """A view for a delegate; one with no agent of its own uses skills as this one."""
        return SkillUseLog(
            agent_id=agent_id or self.agent_id,
            served=served,
            tools=tools,
            tallies=self.tallies,
            own=agent_id is not None,
        )

    def observe(self, tool_name: str, args: Mapping[str, Any]) -> None:
        """Count one finished tool call against the skills it used, if any.

        The load tools are the framework's own and are never renamed; the other two
        are compared by stable id, so a binding that renames them is still read.
        """
        if tool_name in LOAD_TOOLS:
            name = args.get("id")
            if isinstance(name, str) and name in self.served:
                self._tally(name).loaded = True
            return
        tool_id = self.tools.get(tool_name, tool_name)
        if tool_id == RESOURCE_TOOL:
            name = args.get("skill_name")
            if isinstance(name, str) and name in self.served:
                self._tally(name).resource_reads += 1
            return
        if tool_id == LISTING_TOOL or not self._paths:
            return
        texts = [part for text in _strings(args.values()) for part in _unlisted(text)]
        for name, path in self._paths.items():
            if any(path.search(text) for text in texts):
                self._tally(name).workspace_reads += 1

    def records(self) -> list[SkillUseRecord]:
        """What was used, one record per agent and skill, and forget it."""
        records = [
            SkillUseRecord(
                agent_id=agent_id,
                skill_id=tally.served.skill_id,
                skill_version_id=tally.served.version_id,
                projected=tally.served.projected,
                loaded=tally.loaded,
                resource_reads=tally.resource_reads,
                workspace_reads=tally.workspace_reads,
            )
            for (agent_id, _), tally in self.tallies.items()
        ]
        self.tallies.clear()
        return records

    def _tally(self, name: str) -> _Tally:
        served = self.served[name]
        tally = self.tallies.setdefault((self.agent_id, served.skill_id), _Tally(served))
        if self.own:
            tally.served = served
        return tally


def tool_identities(bindings: Iterable[CapabilityBindingSpec]) -> dict[str, str]:
    """Each bound capability's tools by the name the model calls them, to their stable ids."""
    load_builtins()
    return {
        tool.name: tool.id
        for binding in bindings
        if (definition := REGISTRY.get(binding.id)) is not None
        for tool in definition.effective_tools(binding.tool_overrides)
    }


def served_skills(
    skills: Iterable[Skill], bodies: Mapping[UUID, SkillBody]
) -> dict[str, ServedSkill]:
    """The run's stored skills by name, each with the version it serves.

    A skill an eval serves another body for is marked and has no version.

    A skill a proposal would create exists only for the run, with no row to
    attribute a use to, so it is left out.
    """
    return {
        skill.name: ServedSkill(
            skill_id=skill.id,
            projected=skill.id in bodies,
            version_id=None if skill.id in bodies else skill.latest_version_id,
        )
        for skill in skills
        if (body := bodies.get(skill.id)) is None or body.name is None
    }


_COMMANDS = re.compile(r"&&|\|\||[;|\n]")


def _unlisted(text: str) -> list[str]:
    """The text without its shell commands that only list a folder."""
    return [
        command
        for command in _COMMANDS.split(text)
        if (words := command.split()) == [] or words[0] != LISTING_TOOL
    ]


def _strings(values: Iterable[Any]) -> Iterable[str]:
    for value in values:
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            yield from _strings(value.values())
        elif isinstance(value, list | tuple):
            yield from _strings(value)
