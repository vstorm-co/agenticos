"""Explicit authority boundary for global account export and deletion."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.db.models.user import User
from app.db.session import get_table_maintenance_context
from app.repositories import user as user_repo


@asynccontextmanager
async def account_maintenance(
    runtime: AsyncSession, actor: User, *, require_admin: bool
) -> AsyncGenerator[AsyncSession]:
    """Select a global-operation session only after the route authenticated its actor.

    The caller's CurrentUser/CurrentAppAdmin dependency authenticates on the runtime
    connection. Re-read the actor on a newly selected maintenance connection, since
    suspension or removal of app-admin authority must not race into privileged work.
    Self exports always name the authenticated actor; admin exports/deletions also
    require the live app-admin flag here.
    """
    if not actor.is_active:
        raise AuthenticationError(message="Account is disabled")
    if require_admin and not actor.is_app_admin:
        raise AuthorizationError(message="Application administrator required")
    async with get_table_maintenance_context(runtime) as selected:
        if selected is not runtime:
            current = await user_repo.get_by_id(selected, actor.id)
            if current is None or not current.is_active:
                raise AuthenticationError(message="Account is disabled")
            if require_admin and not current.is_app_admin:
                raise AuthorizationError(message="Application administrator required")
        yield selected
