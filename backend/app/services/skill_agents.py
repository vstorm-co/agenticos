"""Which agents read a skill, which version each reads, and moving one of them.

"Uses" has one definition here, shared with the skill page and the line counts: a
version that one of the agent's environments serves binds the skill, itself or
through an inline specialist. An agent that binds it only in its draft is listed
as such and counted on no line.

Moving an agent to another version is a change to the agent, so it is the agent's
to make: the published spec with only that binding changed is published, the same
change goes into the draft, and the draft's other unfinished edits stay unpublished.
"""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec, SkillBindingSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.skill import Skill
from app.db.models.skill_version import SkillFork, SkillVersion
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    skill_check_repo,
    skill_version_repo,
)
from app.schemas.resource_usage import AgentUsage
from app.schemas.skill_version import (
    AgentCheckRef,
    AgentEnvironmentBinding,
    ForkRef,
    SkillAgentList,
    SkillAgentUsage,
    SkillBindingChange,
    SkillBindingChanged,
    SkillBindingRead,
    VersionNumberRef,
    VersionRef,
)
from app.services.access import AGENT, accessible_ids
from app.services.agent_registry import AgentRegistryService, delegation_binding
from app.services.skill_versions import SkillVersionService


@dataclass(frozen=True)
class Line:
    """How one spec reads a skill: main's newest, one main version, or a fork's newest."""

    state: Literal["main", "pinned", "fork"]
    version: int | None = None
    fork_id: UUID | None = None
    via_specialist: str | None = None


def line_of(spec: dict[str, object], skill_id: UUID) -> Line | None:
    """How a stored spec reads the skill, or `None` when it does not bind it.

    The agent's own binding first, then the first inline specialist that binds it.
    Only a spec that names the skill is parsed, and one that no longer parses reads
    nothing that can be shown.
    """
    if str(skill_id) not in json.dumps(spec):
        return None
    try:
        parsed = AgentSpec.model_validate(spec)
    except ValidationError:
        return None

    def read(
        skill_ids: list[UUID], bindings: list[SkillBindingSpec], via: str | None
    ) -> Line | None:
        if skill_id not in skill_ids:
            return None
        binding = next((binding for binding in bindings if binding.skill_id == skill_id), None)
        if binding is None:
            return Line("main", via_specialist=via)
        if binding.version is not None:
            return Line("pinned", version=binding.version, via_specialist=via)
        return Line("fork", fork_id=binding.fork_id, via_specialist=via)

    own = read(parsed.skill_ids, parsed.skill_bindings, None)
    delegation = delegation_binding(parsed)
    if own is not None or delegation is None:
        return own
    try:
        inline = SubagentsConfig.model_validate(delegation.config).inline
    except ValidationError:
        return None
    return next(
        (
            found
            for specialist in inline
            if (found := read(specialist.skill_ids, specialist.skill_bindings, specialist.name))
        ),
        None,
    )


@dataclass(frozen=True)
class LineAgent:
    """An agent whose served version follows a line: the version that runs, and how."""

    agent: Agent
    agent_version: int
    via_specialist: str | None


@dataclass
class _Uses:
    agent: Agent
    served: list[tuple[AgentEnvironment, int, Line]]
    draft: Line | None


@dataclass
class _Resolver:
    skill: Skill
    pinned: dict[int, SkillVersion]
    forks: dict[UUID, SkillFork]
    changes: dict[UUID, int]
    versions: dict[UUID, SkillVersion]

    def read(self, line: Line) -> SkillBindingRead | None:
        """The binding as the page shows it, or `None` for a version or fork that is gone."""
        skill = self.skill
        if line.state == "main":
            assert skill.latest_version_id is not None, "every skill has a main version"
            return SkillBindingRead(
                state="main",
                version=VersionRef(id=skill.latest_version_id, number=skill.version, fork_id=None),
                behind_main=0,
            )
        if line.state == "pinned":
            assert line.version is not None, "a pinned line names its version"
            version = self.pinned.get(line.version)
            if version is None:
                return None
            return SkillBindingRead(
                state="pinned",
                version=VersionRef(id=version.id, number=version.number, fork_id=None),
                behind_main=skill.version - version.number,
            )
        assert line.fork_id is not None, "a fork line names its fork"
        fork = self.forks.get(line.fork_id)
        if fork is None:
            return None
        base = self.versions[fork.base_version_id]
        latest = self.versions[fork.latest_version_id] if fork.latest_version_id else base
        return SkillBindingRead(
            state="fork",
            version=VersionRef(id=latest.id, number=latest.number, fork_id=latest.fork_id),
            fork=ForkRef(
                id=fork.id,
                name=fork.name,
                base_number=base.number,
                changes=self.changes.get(fork.id, 0),
            ),
            behind_main=skill.version - base.number,
        )


class SkillAgentService:
    """The agents of a skill, and moving one of them to another version."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.versions = SkillVersionService(db)
        self.registry = AgentRegistryService(db)

    async def _uses(self, skill: Skill) -> list[_Uses]:
        """Every live agent that binds the skill in a served version or its draft."""
        org = skill.organization_id
        served: dict[UUID, list[tuple[AgentEnvironment, int, Line]]] = {}
        for environment, version in await agent_environment_repo.served(
            self.db, organization_id=org
        ):
            line = line_of(version.spec, skill.id)
            if line is not None:
                served.setdefault(environment.agent_id, []).append(
                    (environment, version.version, line)
                )
        drafts = {
            agent.id: line
            for agent in await agent_repo.drafts_mentioning(
                self.db, str(skill.id), organization_id=org
            )
            if (line := line_of(agent.draft_spec, skill.id)) is not None
        }
        agents = await agent_repo.get_many(
            self.db, sorted(served.keys() | drafts.keys()), organization_id=org
        )
        return [
            _Uses(agent, served.get(agent.id, []), drafts.get(agent.id))
            for agent in sorted(agents.values(), key=lambda agent: agent.name)
            if agent.status != AgentStatus.ARCHIVED.value
        ]

    async def _reader(self, skill: Skill, lines: Sequence[Line]) -> _Resolver:
        """What each line comes to now, read with one query per kind."""
        pinned = await skill_version_repo.get_by_numbers(
            self.db,
            organization_id=skill.organization_id,
            skill_id=skill.id,
            fork_id=None,
            numbers={line.version for line in lines if line.version is not None},
        )
        forks: dict[UUID, SkillFork] = {}
        for fork_id in {line.fork_id for line in lines if line.fork_id is not None}:
            fork = await skill_version_repo.get_fork(
                self.db, fork_id, organization_id=skill.organization_id, skill_id=skill.id
            )
            if fork is not None:
                forks[fork_id] = fork
        changes = await skill_version_repo.count_versions(
            self.db, organization_id=skill.organization_id, fork_ids=list(forks)
        )
        versions = await skill_version_repo.get_versions(
            self.db,
            {fork.base_version_id for fork in forks.values()}
            | {fork.latest_version_id for fork in forks.values() if fork.latest_version_id},
            organization_id=skill.organization_id,
        )
        return _Resolver(skill, pinned, forks, changes, versions)

    async def counts(self, skill: Skill) -> tuple[Counter[UUID], Counter[UUID]]:
        """How many agents' served versions read each skill version, and each fork."""
        uses = [use for use in await self._uses(skill) if use.served]
        default = [_default(use) for use in uses]
        reader = await self._reader(skill, [line for _, _, line in default])
        by_version: Counter[UUID] = Counter()
        by_fork: Counter[UUID] = Counter()
        for _, _, line in default:
            binding = reader.read(line)
            if binding is not None:
                by_version[binding.version.id] += 1
                if binding.fork is not None:
                    by_fork[binding.fork.id] += 1
        return by_version, by_fork

    async def line_agents(self, skill: Skill, fork_id: UUID | None) -> list[LineAgent]:
        """The agents a change to this line reaches: main's followers, or the fork's.

        An agent counts when a served version reads the line - its default
        environment's first, else the first environment that does. Pinned agents,
        other lines and agents bound in a draft alone are not reached.
        """
        found: list[LineAgent] = []
        for use in await self._uses(skill):
            on_line = [
                served
                for served in use.served
                if (served[2].state == "main" if fork_id is None else served[2].fork_id == fork_id)
            ]
            if not on_line:
                continue
            _, number, line = next(
                (served for served in on_line if served[0].is_default), on_line[0]
            )
            found.append(LineAgent(use.agent, number, line.via_specialist))
        return found

    async def fork_users(self, skill: Skill, fork_id: UUID) -> list[Agent]:
        """The agents that read a fork, in a served version or their draft."""
        return [
            use.agent
            for use in await self._uses(skill)
            if any(line.fork_id == fork_id for _, _, line in use.served)
            or (use.draft is not None and use.draft.fork_id == fork_id)
        ]

    async def agents(self, ctx: AuthContext, skill_id: UUID) -> SkillAgentList:
        """The agents that use the skill, as the caller may see them, and how many more."""
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        uses = await self._uses(skill)
        everyone = [use.agent for use in uses]
        visible = await accessible_ids(
            self.db, ctx, everyone, Perm.AGENTS_VIEW, resource_type=AGENT
        )
        shown = [use for use in uses if use.agent.id in visible]
        items = await self._rows(ctx, skill, shown)
        assert skill.latest_version_id is not None, "every skill has a main version"
        return SkillAgentList(
            main_latest=VersionNumberRef(id=skill.latest_version_id, number=skill.version),
            items=items,
            hidden=len(uses) - len(shown),
        )

    async def _rows(
        self, ctx: AuthContext, skill: Skill, uses: Sequence[_Uses]
    ) -> list[SkillAgentUsage]:
        agents = [use.agent for use in uses]
        editable = await accessible_ids(self.db, ctx, agents, Perm.AGENTS_EDIT, resource_type=AGENT)
        publishable = await accessible_ids(
            self.db, ctx, agents, Perm.AGENTS_PUBLISH, resource_type=AGENT
        )
        lines = [line for use in uses for _, _, line in use.served]
        lines += [use.draft for use in uses if use.draft is not None]
        reader = await self._reader(skill, lines)
        checks: dict[UUID, dict[UUID, AgentCheckRef]] = {}
        for agent_id, version_id, found, at in await skill_check_repo.checked_versions(
            self.db,
            organization_id=skill.organization_id,
            skill_id=skill.id,
            agent_ids=[agent.id for agent in agents],
        ):
            checks.setdefault(agent_id, {}).setdefault(
                version_id,
                AgentCheckRef(
                    check_id=found.check_id,
                    version_id=version_id,
                    state=found.state,
                    sample=found.sample,
                    at=at,
                ),
            )
        rows: list[SkillAgentUsage] = []
        for use in uses:
            if use.served:
                environment, number, line = _default(use)
                agent_version: int | None = number
            else:
                assert use.draft is not None, "an agent is listed for a served or a draft binding"
                line, agent_version = use.draft, None
            binding = reader.read(line)
            if binding is None:
                continue
            others = [
                AgentEnvironmentBinding(
                    id=other.id, name=other.name, agent_version=other_number, binding=read
                )
                for other, other_number, other_line in use.served
                if other_line != line and (read := reader.read(other_line)) is not None
            ]
            agent = use.agent
            rows.append(
                SkillAgentUsage(
                    agent=AgentUsage(
                        id=agent.id,
                        name=agent.name,
                        slug=agent.slug,
                        has_avatar=agent.has_avatar,
                        avatar_color=agent.avatar_color,
                    ),
                    via_specialist=line.via_specialist,
                    draft_only=not use.served,
                    binding=binding,
                    agent_version=agent_version,
                    environments=others,
                    draft_differs=use.draft != line,
                    can_change=agent.id in editable,
                    can_publish=agent.id in publishable,
                    checked=checks.get(agent.id, {}).get(binding.version.id),
                    checked_versions=list(checks.get(agent.id, {}).values()),
                )
            )
        return rows

    async def change_binding(
        self, ctx: AuthContext, skill_id: UUID, agent_id: UUID, data: SkillBindingChange
    ) -> SkillBindingChanged:
        """Move one agent to main's newest version, a main version, or a fork.

        With `agents:publish`, the published spec with only this binding changed is
        validated and published as the agent's next version, and environments move
        by their own follow and promotion rules; the draft takes the same change and
        keeps its other edits. With `agents:edit` alone, only the draft changes.

        Raises:
            NotFoundError: The skill, or the agent, is not one the caller may reach.
            BadRequestError: The agent does not bind the skill itself - only through an
                inline specialist, which is changed in the Builder - or the new spec
                does not publish, with the reasons.
        """
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        draft = AgentSpec.model_validate(agent.draft_spec)
        current = (
            None
            if agent.current_version_id is None
            else await agent_repo.get_version(
                self.db, agent.current_version_id, organization_id=ctx.organization_id
            )
        )
        published = None if current is None else AgentSpec.model_validate(current.spec)
        if skill.id not in (draft.skill_ids if published is None else published.skill_ids):
            raise BadRequestError(
                message=(
                    f"'{agent.name}' does not use '{skill.name}' itself. A skill one of its "
                    "specialists uses is changed in the agent's Builder."
                ),
                details={"agent_id": agent.id, "skill_id": skill.id},
            )
        binding = (
            None
            if data.state == "main"
            else SkillBindingSpec(skill_id=skill.id, version=data.version, fork_id=data.fork_id)
        )
        moved_draft = _rebound(draft, skill.id, binding)
        may_publish = published is not None and agent.id in await accessible_ids(
            self.db, ctx, [agent], Perm.AGENTS_PUBLISH, resource_type=AGENT
        )
        if published is None or not may_publish:
            await self.registry.validate_spec(ctx, moved_draft, agent_id=agent.id)
            await self.registry.save_draft(ctx, agent.id, moved_draft)
            return SkillBindingChanged(published=False, usage=await self._row(ctx, skill, agent.id))
        version = await self.registry.publish_spec(
            ctx,
            agent.id,
            _rebound(published, skill.id, binding),
            draft=moved_draft,
            note=data.note or f"Moved {skill.name} to {_described(data)}",
        )
        serving = await agent_environment_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        return SkillBindingChanged(
            published=True,
            agent_version=version.version,
            environments=[env.name for env in serving if env.version_id == version.id],
            usage=await self._row(ctx, skill, agent.id),
        )

    async def _row(self, ctx: AuthContext, skill: Skill, agent_id: UUID) -> SkillAgentUsage | None:
        uses = [use for use in await self._uses(skill) if use.agent.id == agent_id]
        rows = await self._rows(ctx, skill, uses)
        return rows[0] if rows else None


def _default(use: _Uses) -> tuple[AgentEnvironment, int, Line]:
    """The served binding a row shows: the default environment's, else the first one's."""
    return next(
        (served for served in use.served if served[0].is_default),
        use.served[0],
    )


def _rebound(spec: AgentSpec, skill_id: UUID, binding: SkillBindingSpec | None) -> AgentSpec:
    """The spec with this skill's binding replaced; `None` puts it back on main."""
    others = [entry for entry in spec.skill_bindings if entry.skill_id != skill_id]
    return spec.model_copy(
        update={"skill_bindings": others if binding is None else [*others, binding]}
    )


def _described(data: SkillBindingChange) -> str:
    if data.state == "pinned":
        return f"v{data.version}"
    return "a fork" if data.state == "fork" else "main"
