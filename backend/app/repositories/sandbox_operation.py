"""Reading what an agent did in a sandbox, and sweeping it when it is old.

Every read is scoped to one organization and that is not defensive: one `sandboxd`
serves every tenant that registered a connection at its address, so a query without
the organization would read another tenant's log.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sandbox_operation import SandboxOperation


async def list_for_session(
    db: AsyncSession,
    *,
    organization_id: UUID,
    session_key: str | None,
    op: str | None = None,
    failed_only: bool = False,
    query: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[SandboxOperation], int]:
    """One page of a sandbox's log, newest first, and how many match.

    Newest first because the question is "what is it doing" far more often than
    "what did it start with", and the total is what makes a pager honest: the
    service's own log could only ever say how much of its buffer was left.

    The filters narrow the *query* rather than an array the client already holds -
    which is the difference this table exists for. `query` is a case-insensitive
    substring over the operation and its target; a search over `detail` would
    invite somebody to expect contents in there, which is exactly what these rows
    do not carry.
    """
    where = [SandboxOperation.organization_id == organization_id]
    if session_key is not None:
        where.append(SandboxOperation.session_key == session_key)
    if op is not None:
        where.append(SandboxOperation.op == op)
    if failed_only:
        where.append(SandboxOperation.ok.is_(False))
    if query:
        pattern = f"%{query}%"
        where.append(SandboxOperation.op.ilike(pattern) | SandboxOperation.target.ilike(pattern))
    total = (
        await db.execute(select(func.count()).select_from(SandboxOperation).where(*where))
    ).scalar_one()
    rows = await db.execute(
        select(SandboxOperation)
        .where(*where)
        .order_by(SandboxOperation.created_at.desc(), SandboxOperation.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows.scalars()), total


async def operations_seen(db: AsyncSession, *, organization_id: UUID) -> list[str]:
    """Which operations this organization's log actually holds.

    So the filter offers what is there rather than every method a backend could
    have: a filter offering `grep_raw` on a sandbox that has only ever been written
    to is a filter that answers nothing.
    """
    rows = await db.execute(
        select(SandboxOperation.op)
        .where(SandboxOperation.organization_id == organization_id)
        .distinct()
        .order_by(SandboxOperation.op.asc())
    )
    return list(rows.scalars())


async def delete_older_than(db: AsyncSession, *, cutoff: datetime) -> int:
    """Drop every operation recorded before `cutoff`, across every tenant.

    Deliberately unscoped: retention is the deployment's policy, not a tenant's,
    and the sweep reads nothing - it counts what it deleted. Grep for this function
    when auditing cross-tenant writes.
    """
    result = await db.execute(delete(SandboxOperation).where(SandboxOperation.created_at < cutoff))
    return result.rowcount or 0
