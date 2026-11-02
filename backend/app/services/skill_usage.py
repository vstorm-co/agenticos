"""Which agents use a skill.

One definition, shared by every reader: an agent uses a skill when a version an
environment serves binds it, or its draft does - the agent itself or an inline
specialist it defines. Archived agents use nothing; nobody runs them.
"""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.db.models.agent import Agent, AgentStatus
from app.repositories import agent_environment_repo, agent_repo


def _binds(spec: object, skill_id: UUID) -> bool:
    """Whether a stored spec binds the skill; one that no longer parses is taken to.

    Refusing to delete a skill a broken draft may still name is the safe side of
    not knowing: the draft's owner fixes it, and the skill is not lost under them.
    """
    from app.services.eval_suite import binds

    try:
        return binds(AgentSpec.model_validate(spec), "skill", skill_id)
    except ValidationError:
        return True


async def agents_using_skill(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID
) -> list[Agent]:
    """The live agents that use the skill, served or in a draft, in name order."""
    using: set[UUID] = set()
    for environment, version in await agent_environment_repo.served(
        db, organization_id=organization_id
    ):
        if environment.agent_id not in using and _binds(version.spec, skill_id):
            using.add(environment.agent_id)
    for agent in await agent_repo.drafts_mentioning(
        db, str(skill_id), organization_id=organization_id
    ):
        if agent.id not in using and _binds(agent.draft_spec, skill_id):
            using.add(agent.id)
    agents = await agent_repo.get_many(db, sorted(using), organization_id=organization_id)
    return sorted(
        (agent for agent in agents.values() if agent.status != AgentStatus.ARCHIVED.value),
        key=lambda agent: agent.name,
    )
