"""The agent's skills as an Improve session on the agent found them, and the hand-off to a skill.

Agent Improve never changes a skill: a skill is shared, and an edit made for one
agent reaches every agent reading the same line. Where its improver found the
fault in a skill, the session lists the skill with the problems and how far the
agent's version is behind main, and a skill's own Improve starts from them -
on the fork the agent follows, or on main.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.authoring import AuthoringRequest
from app.db.models.skill import Skill
from app.repositories import authoring_repo, skill_repo
from app.schemas.authoring import EvidenceItemRead
from app.schemas.improvement import (
    ImprovementSkill,
    ImprovementSkillProblem,
    ImprovementSkills,
    ImprovementSkillUpdate,
)
from app.schemas.skill_version import SkillAgentList, SkillBindingRead
from app.services.access import SKILL, resolve_access
from app.services.skill_agents import SkillAgentService, line_of


@dataclass(frozen=True)
class SkillSeed:
    """What a skill's Improve starts from when an agent's session hands a skill over.

    Attributes:
        agent_id: The agent whose session found the problems.
        fork_id: The fork that agent follows, which the skill's Improve changes; `None`
            for main, where a pinned agent's problems go too.
        run_ids: The runs the problems cite.
        problems: What the agent's improver found wrong in the skill.
        quotes: The checked quotes those problems cite.
    """

    agent_id: UUID
    fork_id: UUID | None
    run_ids: list[UUID]
    problems: list[str]
    quotes: list[str]


def problems_of(
    requests: Sequence[AuthoringRequest], skill_id: UUID
) -> list[ImprovementSkillProblem]:
    """The problems a session's attempts found in one skill, newest first, each once."""
    found: dict[str, ImprovementSkillProblem] = {}
    for request in requests:
        for item in (request.report or {}).get("skill_problems", []):
            if item["skill_id"] != str(skill_id) or item["problem"] in found:
                continue
            found[item["problem"]] = ImprovementSkillProblem(
                problem=item["problem"],
                evidence=[EvidenceItemRead.model_validate(quote) for quote in item["evidence"]],
            )
    return list(found.values())


class ImprovementSkillService:
    """Reads a session's skills and builds the seed a skill's Improve starts from."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def read(
        self, ctx: AuthContext, agent: Agent, improvement_run_id: UUID
    ) -> ImprovementSkills:
        """Every skill the agent's draft reads, with what the session found in it."""
        spec = AgentSpec.model_validate(agent.draft_spec)
        rows = await skill_repo.get_many(
            self.db, spec.skill_ids, organization_id=ctx.organization_id
        )
        requests = await authoring_repo.requests_of_improvement(
            self.db, improvement_run_id, organization_id=ctx.organization_id
        )
        items: list[ImprovementSkill] = []
        for skill_id in spec.skill_ids:
            skill = rows.get(skill_id)
            if skill is not None:
                items.append(await self._item(ctx, agent, skill, problems_of(requests, skill.id)))
        return ImprovementSkills(items=items)

    async def seed(
        self, ctx: AuthContext, agent: Agent, improvement_run_id: UUID, skill_id: UUID
    ) -> SkillSeed:
        """The seed for a skill's Improve, from what this session found in that skill.

        Raises:
            BadRequestError: The session found no problem in that skill.
        """
        requests = await authoring_repo.requests_of_improvement(
            self.db, improvement_run_id, organization_id=ctx.organization_id
        )
        problems = problems_of(requests, skill_id)
        if not problems:
            raise BadRequestError(
                message="This improvement found no problem in that skill",
                details={"skill_id": skill_id},
            )
        line = line_of(agent.draft_spec, skill_id)
        evidence = [item for problem in problems for item in problem.evidence]
        return SkillSeed(
            agent_id=agent.id,
            fork_id=line.fork_id if line is not None and line.via_specialist is None else None,
            run_ids=list(dict.fromkeys(item.run_id for item in evidence)),
            problems=[problem.problem for problem in problems],
            quotes=[item.quote for item in evidence if item.quote],
        )

    async def _item(
        self,
        ctx: AuthContext,
        agent: Agent,
        skill: Skill,
        problems: list[ImprovementSkillProblem],
    ) -> ImprovementSkill:
        try:
            listed = await SkillAgentService(self.db).agents(ctx, skill.id)
        except NotFoundError, AuthorizationError:
            listed = None
        binding = _binding_of(listed, agent.id)
        return ImprovementSkill(
            skill_id=skill.id,
            name=skill.name,
            binding=binding,
            agents_on_line=None if listed is None or binding is None else _on_line(listed, binding),
            hidden_agents=0 if listed is None else listed.hidden,
            problems=problems,
            can_improve=await resolve_access(
                self.db, ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL
            ),
            update=None if listed is None or binding is None else _update(listed, binding),
        )


def _binding_of(listed: SkillAgentList | None, agent_id: UUID) -> SkillBindingRead | None:
    if listed is None:
        return None
    return next((row.binding for row in listed.items if row.agent.id == agent_id), None)


def _on_line(listed: SkillAgentList, binding: SkillBindingRead) -> int:
    """How many listed agents an Improve of the skill would change: its fork's, or main's.

    A pinned agent hands its problems to main, whose agents on main's newest version
    are the ones that change.
    """
    fork_id = binding.fork.id if binding.fork is not None else None
    return sum(
        not row.draft_only
        and (
            row.binding.state == "main"
            if fork_id is None
            else row.binding.fork is not None and row.binding.fork.id == fork_id
        )
        for row in listed.items
    )


def _update(listed: SkillAgentList, binding: SkillBindingRead) -> ImprovementSkillUpdate | None:
    if binding.state == "main" or binding.behind_main == 0:
        return None
    return ImprovementSkillUpdate(
        kind="update_pinned" if binding.state == "pinned" else "catch_up_fork",
        to_version=listed.main_latest.number,
    )
