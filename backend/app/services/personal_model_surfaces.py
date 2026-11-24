"""Serialize surface admission with publication of the agent it exposes."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.repositories import agent_environment_repo, agent_repo
from app.services.agent_registry import AgentRegistryService


async def require_organization_agent(
    db: AsyncSession,
    ctx: AuthContext,
    agent_id: UUID,
    *,
    perm: Perm = Perm.AGENTS_PUBLISH,
    environment_id: UUID | None = None,
    version_id: UUID | None = None,
) -> None:
    registry = AgentRegistryService(db)
    agent = await registry.get(ctx, agent_id, perm=perm, for_update=True)
    await registry.require_organization_spec(ctx, AgentSpec.model_validate(agent.draft_spec))
    selected = version_id or agent.current_version_id
    if environment_id is not None and version_id is None:
        environment = await agent_environment_repo.get(
            db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None or environment.agent_id != agent.id:
            raise NotFoundError(message="Agent environment not found")
        selected = environment.version_id
    if selected is not None:
        version = await agent_repo.get_version(db, selected, organization_id=ctx.organization_id)
        if version is None or version.agent_id != agent.id:
            raise NotFoundError(message="Agent version not found")
        await registry.require_organization_spec(ctx, AgentSpec.model_validate(version.spec))
