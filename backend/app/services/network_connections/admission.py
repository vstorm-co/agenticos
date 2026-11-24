"""Serialize enrollment with membership removal and tenant/account teardown."""

from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConcurrentChangeError, NotFoundError
from app.db.locks import LOCK_NOT_AVAILABLE, LockScope, try_hold_subject
from app.repositories import network_connection_repo


async def hold_parent(db: AsyncSession, organization_id: UUID) -> None:
    """Hold the org before a child row or queue FK, without waiting under other locks."""
    try:
        async with db.begin_nested():
            exists = await network_connection_repo.lock_parent(db, organization_id=organization_id)
    except DBAPIError as failed:
        if getattr(failed.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
            raise
        raise ConcurrentChangeError(
            message="This organization is being changed; try again"
        ) from failed
    if not exists:
        raise NotFoundError(message="Organization not found")


async def guard_member(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    admission: bool = False,
) -> None:
    """Share account erasure's lock, also held by membership cleanup.

    A removal can already hold the membership row, so this lock never waits.
    Create/connect take the organization exclusively before counting or locking
    a connection. Other mutations take its key share before any child row.
    """
    if not await try_hold_subject(db, LockScope.PERSONAL_DATA_PER_USER, user_id):
        raise ConcurrentChangeError(message="This account is being changed; try again")
    if admission:
        if not await network_connection_repo.lock_quota(db, organization_id=organization_id):
            raise NotFoundError(message="Organization not found")
    else:
        await hold_parent(db, organization_id)
