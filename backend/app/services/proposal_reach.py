"""Which agents a change to a context file or a skill reaches the moment it applies.

Neither has a draft: what an agent's served version reads changes at once, in
every environment that serves a version binding it - itself or through an
inline specialist. A reviewer about to apply such a change is told where it goes
live and which eval suites guard those environments; the owners of those agents
are told once it has.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_environment import AgentEnvironment
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    eval_suite_repo,
    promotion_gate_repo,
)
from app.schemas.eval_suite import DependencyKind
from app.schemas.resource_usage import ReachedAgent
from app.services.access import AGENT, accessible_ids


@dataclass(frozen=True)
class Reach:
    """One agent a change reaches: where it goes live, what runs on it, what waits.

    `runs_now` are the suites a change queues; `at_promotion` the guards of those
    environments that do not run on a change and check the agent when it is next
    promoted.
    """

    agent: Agent
    environments: list[AgentEnvironment]
    runs_now: list[UUID]
    at_promotion: list[UUID]


async def reach(
    db: AsyncSession,
    *,
    organization_id: UUID,
    kind: DependencyKind,
    resource_ids: Sequence[UUID],
) -> dict[UUID, list[Reach]]:
    """For each file or skill, the agents whose served version reads it - archived ones aside."""
    # Imported here: the eval suites reach the agent runner, which records skill proposals.
    from app.services.eval_suite import EvalSuiteService, binds

    served = await agent_environment_repo.served(db, organization_id=organization_id)
    hit: dict[UUID, dict[UUID, list[AgentEnvironment]]] = defaultdict(lambda: defaultdict(list))
    for environment, version in served:
        spec = AgentSpec.model_validate(version.spec)
        for resource_id in resource_ids:
            if binds(spec, kind, resource_id):
                hit[resource_id][environment.agent_id].append(environment)
    agents = await agent_repo.get_many(
        db, sorted({agent for by in hit.values() for agent in by}), organization_id=organization_id
    )
    guards = await promotion_gate_repo.guards_for(
        db,
        [environment.id for by in hit.values() for found in by.values() for environment in found],
        organization_id=organization_id,
    )
    watchers = (
        [
            (suite, AgentSpec.model_validate(version.spec))
            for suite, version in await EvalSuiteService(db).watchers(
                organization_id=organization_id
            )
        ]
        if hit
        else []
    )
    reaches: dict[UUID, list[Reach]] = {}
    for resource_id in resource_ids:
        running: dict[UUID, list[UUID]] = defaultdict(list)
        for suite, spec in watchers if resource_id in hit else []:
            if binds(spec, kind, resource_id):
                running[suite.agent_id].append(suite.id)
        reaches[resource_id] = [
            Reach(
                agents[agent_id],
                found,
                running[agent_id],
                list(
                    dict.fromkeys(
                        guard
                        for environment in found
                        for guard in guards.get(environment.id, [])
                        if guard not in running[agent_id]
                    )
                ),
            )
            for agent_id, found in hit[resource_id].items()
            if agent_id in agents and agents[agent_id].status != AgentStatus.ARCHIVED.value
        ]
    return reaches


async def reached(
    db: AsyncSession, ctx: AuthContext, reaches: Sequence[Reach]
) -> tuple[list[ReachedAgent], int]:
    """The agents as the reader may see them, and how many more it may not.

    A suite is named for a reader of runs - eval suites are read under
    `runs:view` - and counted for anybody else.
    """
    visible = await accessible_ids(
        db, ctx, [item.agent for item in reaches], Perm.AGENTS_VIEW, resource_type=AGENT
    )
    shown = [item for item in reaches if item.agent.id in visible]
    names = (
        await eval_suite_repo.names(
            db,
            sorted({suite for item in shown for suite in [*item.runs_now, *item.at_promotion]}),
            organization_id=ctx.organization_id,
        )
        if ctx.has(Perm.RUNS_VIEW)
        else {}
    )
    return [
        ReachedAgent(
            id=item.agent.id,
            name=item.agent.name,
            environments=[environment.name for environment in item.environments],
            runs_now=[names[suite] for suite in item.runs_now if suite in names],
            runs_now_count=len(item.runs_now),
            at_promotion=[names[suite] for suite in item.at_promotion if suite in names],
            at_promotion_count=len(item.at_promotion),
        )
        for item in sorted(shown, key=lambda item: item.agent.name)
    ], len(reaches) - len(shown)
