"""Catching pinned agents and forks up with main, and moving a fork's changes to main.

Nothing here runs by itself. Every catch-up costs a check on the agents it moves,
so main moving on only marks who it left behind; a person decides which of them
to bring along, and when.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.skill import Skill
from app.repositories import agent_environment_repo, agent_repo, skill_repo, skill_version_repo
from app.schemas.resource_usage import AgentUsage
from app.schemas.skill_version import (
    BehindMain,
    BehindMainList,
    ForkRef,
    ReturnedAgent,
    ReturnedToMain,
    ReturnToMain,
    SkillBindingChange,
    SkillRef,
    VersionNumberRef,
)
from app.services.access import AGENT, SKILL, accessible_ids
from app.services.agent_registry import delegation_binding
from app.services.skill_agents import Line, SkillAgentService, lines_of
from app.services.skill_versions import SkillVersionService, changes_since


@dataclass(frozen=True)
class _Read:
    """One agent reading one skill off main's newest: pinned to a version, or a fork."""

    agent_id: UUID
    skill_id: UUID
    line: Line


class SkillCatchUpService:
    """What main has left behind, and bringing it along on request."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.versions = SkillVersionService(db)
        self.agents = SkillAgentService(db)

    async def behind_main(self, ctx: AuthContext) -> BehindMainList:
        """The pinned agents and the forks main has moved past, as the caller may see them.

        An agent counts by what its default environment serves, as on the skill page.
        A fork is listed when an agent reads it: one nobody reads is behind nobody,
        and is offered for archiving instead. A skill the caller may not view is left
        out whole; a pinned agent the caller may not view is counted, never named.
        """
        org = ctx.organization_id
        reads = _served_reads(await agent_environment_repo.served(self.db, organization_id=org))
        skills = await skill_repo.get_many(
            self.db, sorted({read.skill_id for read in reads}), organization_id=org
        )
        viewable = await accessible_ids(
            self.db, ctx, skills.values(), Perm.SKILLS_VIEW, resource_type=SKILL
        )
        agents = {
            agent.id: agent
            for agent in (
                await agent_repo.get_many(
                    self.db, sorted({read.agent_id for read in reads}), organization_id=org
                )
            ).values()
            if agent.status != AgentStatus.ARCHIVED.value
        }
        reads = [read for read in reads if read.skill_id in viewable and read.agent_id in agents]
        pinned = [read for read in reads if read.line.state == "pinned"]
        items, hidden = await self._pinned(ctx, skills, agents, pinned)
        items += await self._forks(ctx, skills, [read for read in reads if read.line.fork_id])
        items.sort(key=_order)
        return BehindMainList(items=items, total=len(items), hidden=hidden)

    async def return_to_main(
        self, ctx: AuthContext, skill_id: UUID, fork_id: UUID, data: ReturnToMain
    ) -> ReturnedToMain:
        """Move a fork's agents back to main's newest version, then archive the fork once
        nobody reads it.

        Each agent moves as Change version moves it - published with `agents:publish`,
        otherwise in its draft - and one that cannot be moved stays on the fork with the
        reason: an agent the caller may not change, one that reads the fork only through
        a specialist, or one whose new version does not publish. The fork is archived
        only for a caller who may edit the skill.

        Raises:
            NotFoundError: The skill, or the fork, is not one the caller may reach.
        """
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        fork = await skill_version_repo.get_fork(
            self.db, fork_id, organization_id=ctx.organization_id, skill_id=skill.id
        )
        if fork is None:
            raise NotFoundError(message="Fork not found", details={"fork_id": fork_id})
        readers = await self.agents.fork_users(skill, fork.id)
        visible = await accessible_ids(self.db, ctx, readers, Perm.AGENTS_VIEW, resource_type=AGENT)
        wanted = None if data.agent_ids is None else set(data.agent_ids)
        returned: list[ReturnedAgent] = []
        for agent in readers:
            if agent.id not in visible or (wanted is not None and agent.id not in wanted):
                continue
            try:
                moved = await self.agents.change_binding(
                    ctx, skill.id, agent.id, SkillBindingChange(state="main")
                )
            except (NotFoundError, BadRequestError) as refusal:
                returned.append(
                    ReturnedAgent(agent=_usage(agent), published=False, refused=refusal.message)
                )
                continue
            returned.append(
                ReturnedAgent(
                    agent=_usage(agent),
                    published=moved.published,
                    agent_version=moved.agent_version,
                )
            )
        remaining = await self.agents.fork_users(skill, fork.id)
        archived = not remaining and skill.id in await accessible_ids(
            self.db, ctx, [skill], Perm.SKILLS_EDIT, resource_type=SKILL
        )
        if archived:
            await self.versions.archive_fork(ctx, skill.id, fork.id)
        return ReturnedToMain(
            agents=returned,
            hidden=len(readers) - len(visible),
            remaining=len(remaining),
            archived=archived,
        )

    async def _pinned(
        self,
        ctx: AuthContext,
        skills: dict[UUID, Skill],
        agents: dict[UUID, Agent],
        reads: Sequence[_Read],
    ) -> tuple[list[BehindMain], int]:
        """The pinned agents behind main the caller may see, and how many it may not."""
        older = [
            read
            for read in reads
            if read.line.version is not None and read.line.version < skills[read.skill_id].version
        ]
        firsts: dict[UUID, int] = {}
        for read in older:
            assert read.line.version is not None, "a pinned line names its version"
            firsts[read.skill_id] = min(
                read.line.version, firsts.get(read.skill_id, read.line.version)
            )
        changed = await self._changes(ctx, skills, firsts)
        behind = [
            read
            for read in older
            if read.line.version is not None and changed[read.skill_id].get(read.line.version, 0)
        ]
        listed = [agents[read.agent_id] for read in behind]
        visible = await accessible_ids(self.db, ctx, listed, Perm.AGENTS_VIEW, resource_type=AGENT)
        editable = await accessible_ids(self.db, ctx, listed, Perm.AGENTS_EDIT, resource_type=AGENT)
        numbers: dict[UUID, set[int]] = {}
        for read in behind:
            assert read.line.version is not None, "a pinned line names its version"
            numbers.setdefault(read.skill_id, set()).add(read.line.version)
        versions = {
            skill_id: await skill_version_repo.get_by_numbers(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=skill_id,
                fork_id=None,
                numbers=wanted,
            )
            for skill_id, wanted in numbers.items()
        }
        items: list[BehindMain] = []
        for read in behind:
            assert read.line.version is not None, "a pinned line names its version"
            version = versions[read.skill_id].get(read.line.version)
            if read.agent_id not in visible or version is None:
                continue
            skill, agent = skills[read.skill_id], agents[read.agent_id]
            items.append(
                BehindMain(
                    kind="pinned",
                    skill=SkillRef(id=skill.id, name=skill.name),
                    agent=_usage(agent),
                    via_specialist=read.line.via_specialist,
                    agents=1,
                    version=VersionNumberRef(id=version.id, number=version.number),
                    main_latest=_main_latest(skill),
                    behind_main=changed[skill.id][version.number],
                    # A specialist's pin changes in the agent's Builder, not here.
                    can_act=agent.id in editable and read.line.via_specialist is None,
                )
            )
        return items, len({read.agent_id for read in behind if read.agent_id not in visible})

    async def _changes(
        self, ctx: AuthContext, skills: dict[UUID, Skill], firsts: dict[UUID, int]
    ) -> dict[UUID, dict[int, int]]:
        """For each skill, how many main versions after each changed what it says, from the
        oldest one asked about; counted as the skill page counts it."""
        return {
            skill_id: changes_since(
                await skill_version_repo.main_digests(
                    self.db,
                    organization_id=ctx.organization_id,
                    skill_id=skill_id,
                    first=first,
                    last=skills[skill_id].version,
                )
            )
            for skill_id, first in firsts.items()
        }

    async def _forks(
        self, ctx: AuthContext, skills: dict[UUID, Skill], reads: Sequence[_Read]
    ) -> list[BehindMain]:
        """The forks main has moved past, each with how many agents read it."""
        readers: dict[UUID, set[UUID]] = {}
        for read in reads:
            assert read.line.fork_id is not None, "a fork line names its fork"
            readers.setdefault(read.line.fork_id, set()).add(read.agent_id)
        forks = {
            fork.id: fork
            for fork in (
                await skill_version_repo.get_forks(
                    self.db, list(readers), organization_id=ctx.organization_id
                )
            ).values()
            if fork.archived_at is None and fork.skill_id in skills
        }
        bases = await skill_version_repo.get_versions(
            self.db,
            {fork.base_version_id for fork in forks.values()},
            organization_id=ctx.organization_id,
        )
        changes = await skill_version_repo.count_versions(
            self.db, organization_id=ctx.organization_id, fork_ids=list(forks)
        )
        editable = await accessible_ids(
            self.db,
            ctx,
            [skills[fork.skill_id] for fork in forks.values()],
            Perm.SKILLS_EDIT,
            resource_type=SKILL,
        )
        firsts: dict[UUID, int] = {}
        for fork in forks.values():
            number = bases[fork.base_version_id].number
            firsts[fork.skill_id] = min(number, firsts.get(fork.skill_id, number))
        changed = await self._changes(ctx, skills, firsts)
        items: list[BehindMain] = []
        for fork in forks.values():
            skill, base = skills[fork.skill_id], bases[fork.base_version_id]
            if not changed[skill.id].get(base.number, 0):
                continue
            items.append(
                BehindMain(
                    kind="fork",
                    skill=SkillRef(id=skill.id, name=skill.name),
                    fork=ForkRef(
                        id=fork.id,
                        name=fork.name,
                        base_number=base.number,
                        changes=changes[fork.id],
                    ),
                    agents=len(readers[fork.id]),
                    version=VersionNumberRef(id=base.id, number=base.number),
                    main_latest=_main_latest(skill),
                    behind_main=changed[skill.id][base.number],
                    can_act=skill.id in editable,
                )
            )
        return items


def _bound_off_main(spec: AgentSpec) -> set[UUID]:
    """The skills a spec binds to anything but main's newest, its inline specialists' too.

    A spec whose specialists no longer read as a delegation config contributes only
    its own bindings, as the runtime would run it.
    """
    named = {binding.skill_id for binding in spec.skill_bindings}
    delegation = delegation_binding(spec)
    if delegation is None:
        return named
    try:
        inline = SubagentsConfig.model_validate(delegation.config).inline
    except ValidationError:
        return named
    return named | {
        binding.skill_id for specialist in inline for binding in specialist.skill_bindings
    }


def _served_reads(served: Sequence[tuple[AgentEnvironment, AgentVersion]]) -> list[_Read]:
    """What each agent's default environment reads off main: one read per skill for
    the agent itself and one for each inline specialist that reads it its own way.

    Only a spec with a binding is parsed, and one that no longer parses reads main.
    """
    by_agent: dict[UUID, AgentVersion] = {}
    for environment, version in served:
        if environment.is_default or environment.agent_id not in by_agent:
            by_agent[environment.agent_id] = version
    reads: list[_Read] = []
    for agent_id, version in by_agent.items():
        if '"skill_bindings": [{' not in json.dumps(version.spec):
            continue
        try:
            spec = AgentSpec.model_validate(version.spec)
        except ValidationError:
            continue
        for skill_id in sorted(_bound_off_main(spec)):
            reads += [
                _Read(agent_id, skill_id, line)
                for line in lines_of(version.spec, skill_id)
                if line.state != "main"
            ]
    return reads


def _order(item: BehindMain) -> tuple[int, str, str]:
    """Furthest behind first, then by skill, then by the agent or fork."""
    if item.agent is not None:
        named = item.agent.name
    else:
        assert item.fork is not None, "an item is a pinned agent or a fork"
        named = item.fork.name
    return (-item.behind_main, item.skill.name.lower(), named.lower())


def _main_latest(skill: Skill) -> VersionNumberRef:
    assert skill.latest_version_id is not None, "every skill has a main version"
    return VersionNumberRef(id=skill.latest_version_id, number=skill.version)


def _usage(agent: Agent) -> AgentUsage:
    return AgentUsage(
        id=agent.id,
        name=agent.name,
        slug=agent.slug,
        has_avatar=agent.has_avatar,
        avatar_color=agent.avatar_color,
    )
