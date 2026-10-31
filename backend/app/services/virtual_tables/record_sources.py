"""Write provenance derived from trusted execution context, never submitted cells."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.repositories import agent as agent_repo
from app.repositories import api_key as api_key_repo
from app.repositories import user as user_repo
from app.repositories import workflow as workflow_repo
from app.schemas.virtual_table import RecordSource
from app.services.workflow_execution import context as workflow_context

_agent: ContextVar[tuple[UUID | None] | None] = ContextVar("table_record_agent", default=None)


@contextmanager
def from_agent(agent_id: UUID | None) -> Generator[None]:
    token = _agent.set((agent_id,))
    try:
        yield
    finally:
        _agent.reset(token)


async def _agent_source(db: AsyncSession, ctx: AuthContext, agent_id: UUID | None) -> RecordSource:
    agent = (
        None
        if agent_id is None
        else await agent_repo.get(db, agent_id, organization_id=ctx.organization_id)
    )
    return RecordSource(
        kind="agent",
        id=agent_id,
        name=agent.name if agent else "Agent",
        slug=agent.slug if agent else None,
        has_avatar=agent.has_avatar if agent else False,
        avatar_color=agent.avatar_color if agent else None,
    )


async def source_for(db: AsyncSession, ctx: AuthContext) -> RecordSource:
    acting = _agent.get()
    if acting is not None:
        return await _agent_source(db, ctx, acting[0])
    if ctx.api_key_id is not None:
        key = await api_key_repo.get(db, ctx.api_key_id, organization_id=ctx.organization_id)
        if key is not None:
            if key.internal:
                return await _agent_source(db, ctx, key.source_agent_id)
            return RecordSource(kind="api", id=key.id, name=key.name)
        return RecordSource(kind="api", id=ctx.api_key_id, name="API")
    dispatch = workflow_context.active()
    if dispatch is not None:
        workflow = (
            None
            if dispatch.workflow_id is None
            else await workflow_repo.get(
                db, dispatch.workflow_id, organization_id=ctx.organization_id
            )
        )
        return RecordSource(
            kind="workflow", id=dispatch.workflow_id, name=workflow.name if workflow else "Workflow"
        )
    if ctx.user_id is not None:
        user = await user_repo.get_by_id(db, ctx.user_id)
        return RecordSource(
            kind="user", id=ctx.user_id, name=(user.full_name or user.email) if user else "User"
        )
    return RecordSource(kind="system", name="System")
