"""Which agents read a skill, which version each reads, and moving one of them.

"Uses" has one definition here, shared with the skill page and the line counts: a
version that one of the agent's environments serves binds the skill, itself or
through an inline specialist. An agent and its specialists each read their own
binding, so one spec can read the skill on more than one line. An agent that binds
it only in its draft is listed as such and counted on no line.

Moving an agent to another version is a change to the agent, so it is the agent's
to make: its newest published spec with only that binding changed is published, the
same change goes into the draft, and the draft's other unfinished edits stay
unpublished.
"""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec, SkillBindingSpec
from app.core.exceptions import BadRequestError, InUseError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.skill import Skill
from app.db.models.skill_check import CheckOutcome
from app.db.models.skill_version import SkillFork, SkillVersion
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    promotion_gate_repo,
    skill_check_repo,
    skill_usage_repo,
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
from app.services.agent_registry import (
    DELEGATION_CAPABILITY_ID,
    AgentRegistryService,
    delegation_binding,
)
from app.services.skill_versions import SkillVersionService, changes_since


@dataclass(frozen=True)
class Line:
    """How one spec reads a skill: main's newest, one main version, or a fork's newest."""

    state: Literal["main", "pinned", "fork"]
    version: int | None = None
    fork_id: UUID | None = None
    via_specialist: str | None = None


def lines_of(spec: dict[str, object], skill_id: UUID) -> list[Line]:
    """Every way a stored spec reads the skill: the agent's own binding first, then
    each inline specialist that binds it, in the order they are defined.

    Only a spec that names the skill is parsed. One that no longer parses reads
    nothing that can be shown, and specialists that no longer parse add nothing.
    """
    if str(skill_id) not in json.dumps(spec):
        return []
    try:
        parsed = AgentSpec.model_validate(spec)
    except ValidationError:
        return []

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
    lines = [] if own is None else [own]
    delegation = delegation_binding(parsed)
    if delegation is None:
        return lines
    try:
        inline = SubagentsConfig.model_validate(delegation.config).inline
    except ValidationError:
        return lines
    return lines + [
        found
        for specialist in inline
        if (found := read(specialist.skill_ids, specialist.skill_bindings, specialist.name))
    ]


@dataclass(frozen=True)
class LineAgent:
    """An agent whose served version follows a line: the version that runs, and how."""

    agent: Agent
    agent_version: int
    via_specialist: str | None


@dataclass
class _Uses:
    agent: Agent
    served: list[tuple[AgentEnvironment, int, list[Line]]]
    draft: list[Line]


@dataclass
class _Resolver:
    skill: Skill
    pinned: dict[int, SkillVersion]
    forks: dict[UUID, SkillFork]
    changes: dict[UUID, int]
    versions: dict[UUID, SkillVersion]
    behind_main: dict[int, int]
    """How many main versions after each one changed what the skill says, from the
    oldest any line here is on."""

    def behind(self, number: int) -> int:
        return self.behind_main.get(number, 0)

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
                behind_main=self.behind(version.number),
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
            behind_main=self.behind(base.number),
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
        served: dict[UUID, list[tuple[AgentEnvironment, int, list[Line]]]] = {}
        for environment, version in await agent_environment_repo.served_mentioning(
            self.db, [str(skill.id)], organization_id=org
        ):
            if lines := lines_of(version.spec, skill.id):
                served.setdefault(environment.agent_id, []).append(
                    (environment, version.version, lines)
                )
        drafts = {
            agent.id: lines
            for agent in await agent_repo.drafts_mentioning(
                self.db, str(skill.id), organization_id=org
            )
            if (lines := lines_of(agent.draft_spec, skill.id))
        }
        agents = await agent_repo.get_many(
            self.db, sorted(served.keys() | drafts.keys()), organization_id=org
        )
        return [
            _Uses(agent, served.get(agent.id, []), drafts.get(agent.id, []))
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
        oldest = [version.number for version in pinned.values()]
        oldest += [versions[fork.base_version_id].number for fork in forks.values()]
        behind = changes_since(
            await skill_version_repo.main_digests(
                self.db,
                organization_id=skill.organization_id,
                skill_id=skill.id,
                first=min(oldest),
                last=skill.version,
            )
            if oldest
            else []
        )
        return _Resolver(skill, pinned, forks, changes, versions, behind)

    async def counts(self, skill: Skill) -> tuple[Counter[UUID], Counter[UUID]]:
        """How many agents' served versions read each skill version, and each fork.

        An agent counts once on each version and fork it reads in any environment that
        serves it, its specialists' included.
        """
        uses = [use for use in await self._uses(skill) if use.served]
        reader = await self._reader(
            skill, [line for use in uses for _, _, lines in use.served for line in lines]
        )
        by_version: Counter[UUID] = Counter()
        by_fork: Counter[UUID] = Counter()
        for use in uses:
            bindings = [
                binding
                for _, _, lines in use.served
                for line in lines
                if (binding := reader.read(line)) is not None
            ]
            by_version.update({binding.version.id for binding in bindings})
            by_fork.update({binding.fork.id for binding in bindings if binding.fork is not None})
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
                (environment, number, line)
                for environment, number, lines in use.served
                for line in lines
                if (line.state == "main" if fork_id is None else line.fork_id == fork_id)
            ]
            if not on_line:
                continue
            _, number, line = next(
                (served for served in on_line if served[0].is_default), on_line[0]
            )
            found.append(LineAgent(use.agent, number, line.via_specialist))
        return found

    async def pinned_agent(
        self, skill: Skill, agent_id: UUID
    ) -> tuple[LineAgent, int] | str | None:
        """The agent, as its served version reads the skill itself, and the main version
        it stays on.

        The name of the inline specialist that pins it instead, when only one of the
        agent's specialists stays on a main version - that is changed in the Builder -
        and `None` when no reader of the agent's served version does.
        """
        for use in await self._uses(skill):
            if use.agent.id != agent_id or not use.served:
                continue
            served = sorted(use.served, key=lambda entry: not entry[0].is_default)
            own = next(
                (
                    (number, line)
                    for _, number, lines in served
                    if (line := _by_reader(lines, None)) is not None
                ),
                None,
            )
            if own is not None and own[1].state == "pinned" and own[1].version is not None:
                return LineAgent(use.agent, own[0], None), own[1].version
            return next(
                (
                    line.via_specialist
                    for _, _, lines in served
                    for line in lines
                    if line.state == "pinned" and line.via_specialist is not None
                ),
                None,
            )
        return None

    async def fork_users(self, skill: Skill, fork_id: UUID) -> list[Agent]:
        """The agents that read a fork, themselves or through a specialist, in a served
        version or their draft."""
        return [
            use.agent
            for use in await self._uses(skill)
            if any(line.fork_id == fork_id for _, _, lines in use.served for line in lines)
            or any(line.fork_id == fork_id for line in use.draft)
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
            hidden=len({use.agent.id for use in uses} - visible),
        )

    async def _rows(
        self, ctx: AuthContext, skill: Skill, uses: Sequence[_Uses]
    ) -> list[SkillAgentUsage]:
        agents = [use.agent for use in uses]
        editable = await accessible_ids(self.db, ctx, agents, Perm.AGENTS_EDIT, resource_type=AGENT)
        publishable = await accessible_ids(
            self.db, ctx, agents, Perm.AGENTS_PUBLISH, resource_type=AGENT
        )
        lines = [line for use in uses for _, _, served in use.served for line in served]
        lines += [line for use in uses for line in use.draft]
        reader = await self._reader(skill, lines)
        checks: dict[UUID, dict[UUID, AgentCheckRef]] = {}
        # What a check found on an agent is eval results, read like a check itself.
        checked = [] if not ctx.has(Perm.RUNS_VIEW) else agents
        for agent_id, version_id, found, at in await skill_check_repo.checked_versions(
            self.db,
            organization_id=skill.organization_id,
            skill_id=skill.id,
            agent_ids=[agent.id for agent in checked],
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
        answered: dict[UUID, list[UUID]] = {}
        for agent_id, version_id in await skill_usage_repo.answered_versions(
            self.db,
            organization_id=skill.organization_id,
            skill_id=skill.id,
            agent_ids=[agent.id for agent in checked],
        ):
            answered.setdefault(agent_id, []).append(version_id)
        rows: list[SkillAgentUsage] = []
        for use in uses:
            # The default environment first: a reader's row shows what it serves there.
            served = sorted(use.served, key=lambda entry: not entry[0].is_default)
            draft = {line.via_specialist: line for line in use.draft}
            readers = [line.via_specialist for _, _, lines in served for line in lines]
            for via in dict.fromkeys([*readers, *draft]):
                primary = next(
                    (
                        (environment, number, found)
                        for environment, number, lines in served
                        if (found := _by_reader(lines, via)) is not None
                    ),
                    None,
                )
                if primary is None:
                    shown, agent_version, line = None, None, draft[via]
                else:
                    shown, agent_version, line = primary
                binding = reader.read(line)
                if binding is None:
                    continue
                others = [
                    AgentEnvironmentBinding(
                        id=other.id, name=other.name, agent_version=other_number, binding=read
                    )
                    for other, other_number, other_lines in served
                    if other is not shown
                    and (other_line := _by_reader(other_lines, via)) is not None
                    and other_line != line
                    and (read := reader.read(other_line)) is not None
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
                        via_specialist=via,
                        draft_only=primary is None,
                        binding=binding,
                        agent_version=agent_version,
                        environments=others,
                        draft_differs=draft.get(via) != line,
                        can_change=agent.id in editable and via is None and None in draft,
                        can_publish=agent.id in publishable,
                        checked=checks.get(agent.id, {}).get(binding.version.id),
                        checked_versions=list(checks.get(agent.id, {}).values()),
                        answered_with=answered.get(agent.id, []),
                    )
                )
        return rows

    async def change_binding(
        self, ctx: AuthContext, skill_id: UUID, agent_id: UUID, data: SkillBindingChange
    ) -> SkillBindingChanged:
        """Move one agent to main's newest version, a main version, or a fork.

        The agent's draft says whether it uses the skill itself, as the Builder shows
        it. With `agents:publish`, and when its newest published version binds the
        skill too, that version's spec with only this binding changed is validated
        and published as the agent's next version, and environments move by their own
        follow and promotion rules; the draft takes the same change and keeps its
        other edits. Otherwise - `agents:edit` alone, an agent never published, or a
        skill not published yet - only the draft changes, and only the new binding is
        checked, since a draft is allowed to be unfinished.

        A pinned agent moving to main may name the finished check of main's newest
        version on it (`check_id`): the move is then refused when that version made
        the agent worse, or the agent or main changed since, and the check is closed
        with it, which marks the agent checked on that version.

        Raises:
            NotFoundError: The skill, or the agent, is not one the caller may reach.
            BadRequestError: The draft does not bind the skill itself - only through an
                inline specialist, which is changed in the Builder, or not at all - or
                the version or fork cannot be bound, or the new spec does not publish,
                with the reasons; or `check_id` refuses the move, as
                :meth:`SkillCheckService.checked_update` says.
            ConcurrentChangeError: `check_id` measured an agent or a main that moved since.
        """
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        if data.check_id is not None:
            # Imported here: the check service reads the agents of a skill through this one.
            from app.services.skill_check import SkillCheckService

            # Read unlocked first, so an agent the caller may not edit is not found
            # before anything about its check is said. The decision then locks the
            # skill, the check and the agent, the order every write to a skill takes.
            await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
            checks = SkillCheckService(self.db)
            check = await checks.checked_update(
                ctx, skill.id, agent_id, data.check_id, acknowledged=data.acknowledge_unknown
            )
            assert check.candidate_version_id is not None, "an update names main's version"
            await checks.record_decision(
                ctx,
                check,
                CheckOutcome.APPLY,
                check.candidate_version_id,
                acknowledged=data.acknowledge_unknown,
            )
        agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        draft = AgentSpec.model_validate(agent.draft_spec)
        if skill.id not in draft.skill_ids:
            raise BadRequestError(
                message=(
                    f"'{agent.name}' does not use '{skill.name}' itself. A skill one of its "
                    "specialists uses is changed in the agent's Builder."
                    if lines_of(agent.draft_spec, skill.id)
                    else f"'{agent.name}' does not use '{skill.name}'."
                ),
                details={"agent_id": agent.id, "skill_id": skill.id},
            )
        binding = (
            None
            if data.state == "main"
            else SkillBindingSpec(skill_id=skill.id, version=data.version, fork_id=data.fork_id)
        )
        moved_draft = _rebound(draft, skill.id, binding)
        newest = await agent_repo.newest_version(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        published = None if newest is None else AgentSpec.model_validate(newest.spec)
        if (
            published is None
            or skill.id not in published.skill_ids
            or agent.id
            not in await accessible_ids(
                self.db, ctx, [agent], Perm.AGENTS_PUBLISH, resource_type=AGENT
            )
        ):
            problems = await self.registry.skill_problems(
                ctx, [skill.id], [] if binding is None else [binding]
            )
            if problems:
                raise BadRequestError(
                    message=f"'{skill.name}' cannot be bound that way",
                    details={"problems": problems},
                )
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
        """The agent's own row as it reads now, or `None` once it no longer reads the skill."""
        uses = [use for use in await self._uses(skill) if use.agent.id == agent_id]
        rows = await self._rows(ctx, skill, uses)
        return next((row for row in rows if row.via_specialist is None), None)

    async def remove_skill(self, ctx: AuthContext, skill: Skill, using: Sequence[Agent]) -> None:
        """Take the skill out of every agent that uses it, so that it can be deleted.

        Each agent loses the skill from its draft, itself and in every inline
        specialist. When an environment that follows publishes serves a version
        using it, the newest published version without the skill is published as
        the agent's next version, which moves those environments, as Change version
        does; otherwise only the draft changes. All or nothing: the agents are
        checked before any of them changes, and a refusal leaves every one as it was.

        Raises:
            InUseError: An agent is hidden from the caller, or one the caller may not
                change: no `agents:edit`, no `agents:publish` where a version has to
                be published, or a spec that no longer reads. Or an environment
                that waits for promotion serves a version using the skill: only a
                promotion moves it, and that is its owner's decision. `details`
                names each, beside the agents and hidden count a plain refusal gives.
        """
        visible = await accessible_ids(self.db, ctx, using, Perm.AGENTS_VIEW, resource_type=AGENT)
        editable = await accessible_ids(self.db, ctx, using, Perm.AGENTS_EDIT, resource_type=AGENT)
        named = [agent for agent in using if agent.id in visible]
        hidden = len(using) - len(named)
        blocked = [agent for agent in named if agent.id not in editable]
        if hidden or blocked:
            raise _cannot_remove(skill, named, hidden, blocked, [])
        publishable = await accessible_ids(
            self.db, ctx, named, Perm.AGENTS_PUBLISH, resource_type=AGENT
        )
        removals: list[_Removal] = []
        waiting: list[tuple[Agent, list[str]]] = []
        for agent in sorted(named, key=lambda agent: agent.id):
            removal = await self._removal(ctx, skill, agent.id)
            if removal is None or (
                removal.publish_from is not None and agent.id not in publishable
            ):
                blocked.append(agent)
            elif removal.waiting:
                waiting.append((agent, removal.waiting))
            else:
                removals.append(removal)
        if blocked or waiting:
            raise _cannot_remove(skill, named, 0, blocked, waiting)
        for removal in removals:
            if removal.publish_from is not None:
                await self._publish_without(ctx, skill, removal)
            else:
                await self.registry.save_draft(ctx, removal.agent.id, removal.draft)

    async def _publish_without(self, ctx: AuthContext, skill: Skill, removal: _Removal) -> None:
        """Publish the newest published spec without the skill, naming the agent when it
        does not publish: the request names no agent, so the refusal has to."""
        assert removal.publish_from is not None, "only a removal that publishes comes here"
        agent = removal.agent
        try:
            await self.registry.publish_spec(
                ctx,
                agent.id,
                without_skill(removal.publish_from, skill.id),
                draft=removal.draft,
                note=f"Removed {skill.name} before it was deleted",
            )
        except BadRequestError as exc:
            raise BadRequestError(
                message=(
                    f"'{agent.name}' does not publish without '{skill.name}': {exc.message}. "
                    "Fix the agent, then delete the skill again."
                ),
                details={
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "problems": (exc.details or {}).get("problems", []),
                },
            ) from exc

    async def _removal(self, ctx: AuthContext, skill: Skill, agent_id: UUID) -> _Removal | None:
        """What taking the skill out of one agent writes, or `None` for an unreadable spec.

        A served spec that does not name the skill is left alone however it reads; one
        that names it and no longer parses may bind it, so it refuses. The agent is
        locked, as every change to it is.
        """
        agent = await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        draft = _parsed(agent.draft_spec)
        if draft is None:
            return None
        environments = await agent_environment_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        versions = await agent_repo.get_versions_by_ids(
            self.db,
            [environment.version_id for environment in environments],
            organization_id=ctx.organization_id,
        )
        serving: list[AgentEnvironment] = []
        for environment in environments:
            served = versions[environment.version_id].spec
            if lines_of(served, skill.id):
                serving.append(environment)
            elif str(skill.id) in json.dumps(served) and _parsed(served) is None:
                return None
        # A follower its guard suites hold is not moved by a publish: it waits for them as
        # one that waits for promotion does.
        guarded = await promotion_gate_repo.guards_for(
            self.db,
            [environment.id for environment in serving],
            organization_id=ctx.organization_id,
        )
        moving = [env for env in serving if env.tracks_latest and env.id not in guarded]
        publish_from: AgentSpec | None = None
        if moving:
            newest = await agent_repo.newest_version(
                self.db, agent_id=agent.id, organization_id=ctx.organization_id
            )
            assert newest is not None, "an environment serves one of the agent's versions"
            publish_from = _parsed(newest.spec)
            if publish_from is None:
                return None
        return _Removal(
            agent=agent,
            draft=without_skill(draft, skill.id),
            publish_from=publish_from,
            waiting=[env.name for env in serving if env not in moving],
        )


@dataclass(frozen=True)
class _Removal:
    """What taking a skill out of one agent writes."""

    agent: Agent
    draft: AgentSpec
    publish_from: AgentSpec | None
    """The newest published spec, published again without the skill; `None` when no
    environment that follows publishes serves a version using it."""
    waiting: list[str]
    """Environments serving a version using the skill that a publish does not move: they
    wait for promotion, or for their guard suites."""


def _parsed(spec: dict[str, Any]) -> AgentSpec | None:
    try:
        return AgentSpec.model_validate(spec)
    except ValidationError:
        return None


def _cannot_remove(
    skill: Skill,
    named: Sequence[Agent],
    hidden: int,
    blocked: Sequence[Agent],
    waiting: Sequence[tuple[Agent, list[str]]],
) -> InUseError:
    reasons: list[str] = []
    if hidden:
        reasons.append(
            f"{hidden} agent{'' if hidden == 1 else 's'} using it {'is' if hidden == 1 else 'are'} "
            "hidden from you"
        )
    if blocked:
        names = ", ".join(f"'{agent.name}'" for agent in blocked)
        reasons.append(f"you cannot change {names}")
    for agent, environments in waiting:
        reasons.append(
            f"'{agent.name}' serves it in {', '.join(environments)}, which only a promotion moves"
        )
    return InUseError(
        message=(
            f"'{skill.name}' was not removed from any agent: {'; '.join(reasons)}. "
            "Ask their owners to remove it, then delete it."
        ),
        details={
            "agents": [{"id": agent.id, "name": agent.name} for agent in named],
            "hidden": hidden,
            "not_editable": [{"id": agent.id, "name": agent.name} for agent in blocked],
            "waiting": [
                {"id": agent.id, "name": agent.name, "environments": environments}
                for agent, environments in waiting
            ],
        },
    )


def without_skill(spec: AgentSpec, skill_id: UUID) -> AgentSpec:
    """The spec with the skill and its binding gone, from the agent and every inline
    specialist; the delegation's config is otherwise kept as it was stored."""
    capabilities = [
        binding.model_copy(update={"config": _config_without(binding.config, skill_id)})
        if binding.id == DELEGATION_CAPABILITY_ID
        else binding
        for binding in spec.capabilities
    ]
    return spec.model_copy(
        update={
            "skill_ids": [found for found in spec.skill_ids if found != skill_id],
            "skill_bindings": [
                binding for binding in spec.skill_bindings if binding.skill_id != skill_id
            ],
            "capabilities": capabilities,
        }
    )


def _config_without(config: dict[str, Any], skill_id: UUID) -> dict[str, Any]:
    """The delegation's config with the skill gone from each inline specialist, edited
    as stored so nothing else in it changes; one that no longer reads is kept as it is."""
    try:
        SubagentsConfig.model_validate(config)
    except ValidationError:
        return config
    if not config.get("inline"):
        return config
    wanted = str(skill_id)
    return {
        **config,
        "inline": [
            {
                **specialist,
                "skill_ids": [
                    found for found in specialist.get("skill_ids", []) if str(found) != wanted
                ],
                "skill_bindings": [
                    binding
                    for binding in specialist.get("skill_bindings", [])
                    if str(binding["skill_id"]) != wanted
                ],
            }
            for specialist in config["inline"]
        ],
    }


def _by_reader(lines: Sequence[Line], via_specialist: str | None) -> Line | None:
    """The line the agent itself, or one of its specialists, reads."""
    return next((line for line in lines if line.via_specialist == via_specialist), None)


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
