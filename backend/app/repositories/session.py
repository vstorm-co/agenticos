"""Session repository (PostgreSQL async)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.session import Session


async def get_by_id(db: AsyncSession, session_id: UUID) -> Session | None:
    """Get session by ID."""
    return await db.get(Session, session_id)


async def get_by_refresh_token_hash(db: AsyncSession, token_hash: str) -> Session | None:
    """Get session by refresh token hash."""
    result = await db.execute(
        select(Session).where(
            Session.refresh_token_hash == token_hash,
            Session.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


def _open(query: Select[tuple[Any]]) -> Select[tuple[Any]]:
    """Narrow a session query to the ones actually still usable.

    `is_active` alone is not that. A session is deactivated when somebody signs
    out or an administrator revokes it, but nothing sweeps the ones that simply
    ran out: the row stays `is_active` until the next refresh finds it expired
    and declines it. So a query on `is_active` counts sessions that cannot be
    used again, which is how the admin drawer reported open sessions for an
    account whose every session had lapsed (#1256).
    """
    return query.where(Session.is_active.is_(True), Session.expires_at > datetime.now(UTC))


async def get_user_sessions(
    db: AsyncSession,
    user_id: UUID,
    *,
    open_only: bool = True,
    skip: int = 0,
    limit: int | None = None,
) -> list[Session]:
    """Get sessions for a user, most recently used first.

    `limit` of None returns every session, which is what the callers that
    revoke or validate one need. The listing route passes a page.

    `open_only=False` is the whole history, which is what answers "when were
    they last here": somebody who has signed out has no open session and has
    very much been here.
    """
    query = select(Session).where(Session.user_id == user_id)
    if open_only:
        query = _open(query)
    # `last_used_at` alone is not a total order - a user who signs in twice in
    # the same request cycle gets two rows with the same timestamp, and an
    # unstable order means a row can appear on two pages or on neither. `id`
    # breaks the tie.
    query = query.order_by(Session.last_used_at.desc(), Session.id).offset(skip)
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_user_sessions(
    db: AsyncSession,
    user_id: UUID,
    *,
    open_only: bool = True,
) -> int:
    """How many sessions the user has, for the page count."""
    query = select(func.count(Session.id)).where(Session.user_id == user_id)
    if open_only:
        query = _open(query)
    return (await db.execute(query)).scalar_one()


async def create(
    db: AsyncSession,
    *,
    user_id: UUID,
    refresh_token_hash: str,
    expires_at: datetime,
    device_name: str | None = None,
    device_type: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Session:
    """Create a new session."""
    session = Session(
        user_id=user_id,
        refresh_token_hash=refresh_token_hash,
        expires_at=expires_at,
        device_name=device_name,
        device_type=device_type,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def update_last_used(db: AsyncSession, session_id: UUID) -> None:
    """Update session last used timestamp."""
    await db.execute(
        update(Session).where(Session.id == session_id).values(last_used_at=datetime.now(UTC))
    )
    await db.flush()


async def deactivate(db: AsyncSession, session_id: UUID) -> Session | None:
    """Deactivate a session (logout)."""
    session = await get_by_id(db, session_id)
    if session:
        session.is_active = False
        db.add(session)
        await db.flush()
    return session


async def deactivate_all_user_sessions(db: AsyncSession, user_id: UUID) -> int:
    """Deactivate all sessions for a user. Returns count of deactivated sessions."""
    result = await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.is_active.is_(True))
        .values(is_active=False)
    )
    await db.flush()
    return getattr(result, "rowcount", 0) or 0


async def deactivate_by_refresh_token_hash(db: AsyncSession, token_hash: str) -> Session | None:
    """Deactivate session by refresh token hash."""
    session = await get_by_refresh_token_hash(db, token_hash)
    if session:
        session.is_active = False
        db.add(session)
        await db.flush()
    return session
