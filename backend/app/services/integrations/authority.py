"""A shared account is delegated by its binding author, never by a guessed ID."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.mcp_connection import McpConnection
from app.repositories import agent_repo, agent_run_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.access import MCP_CONNECTION, decider_context, resolve_access


async def authorize(db: AsyncSession, account: McpConnection, ctx: AuthContext) -> None:
    if not await resolve_access(db, ctx, account, Perm.MCP_MANAGE, resource_type=MCP_CONNECTION):
        raise AuthorizationError(message="This account is not available for you to bind")


async def run_author(
    db: AsyncSession,
    *,
    organization_id: UUID,
    person_id: UUID | None,
    agent_run_id: UUID | None,
    workflow_run_id: UUID | None,
) -> AuthContext:
    author = person_id
    if agent_run_id is not None:
        run = await agent_run_repo.get_run(db, agent_run_id, organization_id=organization_id)
        if run is None:
            raise AuthorizationError(message="This integration run no longer exists")
        if run.agent_version_id is not None:
            version = await agent_repo.get_version(
                db, run.agent_version_id, organization_id=organization_id
            )
            author = version.published_by_user_id if version else None
        else:
            author = run.user_id
    if workflow_run_id is not None:
        workflow_run = await workflow_run_repo.get_run(
            db, workflow_run_id, organization_id=organization_id
        )
        if workflow_run is None:
            raise AuthorizationError(message="This integration workflow run no longer exists")
        if workflow_run.workflow_version_id is not None:
            workflow_version = await workflow_repo.get_version(
                db, workflow_run.workflow_version_id, organization_id=organization_id
            )
            author = workflow_version.published_by_user_id if workflow_version else None
        else:
            author = workflow_run.execution_principal_user_id
    context = (
        await decider_context(db, organization_id=organization_id, user_id=author)
        if author
        else None
    )
    if context is None:
        raise AuthorizationError(
            message="The integration binding author is no longer authorized in this organization"
        )
    return context
