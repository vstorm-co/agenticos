"""Data access for sandbox connections."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sandbox_connection import SandboxConnection


async def get(
    db: AsyncSession, connection_id: UUID, *, organization_id: UUID
) -> SandboxConnection | None:
    """One connection, inside its organization.

    The scope is not decoration: without it a connection id from another tenant
    resolves, and what it resolves to is a host somebody else's agents run on.
    """
    result = await db.execute(
        select(SandboxConnection).where(
            SandboxConnection.id == connection_id,
            SandboxConnection.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_default(db: AsyncSession, *, organization_id: UUID) -> SandboxConnection | None:
    result = await db.execute(
        select(SandboxConnection).where(
            SandboxConnection.organization_id == organization_id,
            SandboxConnection.is_default.is_(True),
            SandboxConnection.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(
    db: AsyncSession, *, organization_id: UUID, name: str
) -> SandboxConnection | None:
    result = await db.execute(
        select(SandboxConnection).where(
            SandboxConnection.organization_id == organization_id,
            SandboxConnection.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_for_organization(
    db: AsyncSession, *, organization_id: UUID
) -> list[SandboxConnection]:
    result = await db.execute(
        select(SandboxConnection)
        .where(SandboxConnection.organization_id == organization_id)
        .order_by(SandboxConnection.is_default.desc(), SandboxConnection.name)
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    name: str,
    kind: str,
    base_url: str | None = None,
    secret_id: UUID | None = None,
    default_runtime: str | None = None,
    is_default: bool = False,
) -> SandboxConnection:
    connection = SandboxConnection(
        organization_id=organization_id,
        name=name,
        kind=kind,
        base_url=base_url,
        secret_id=secret_id,
        default_runtime=default_runtime,
        is_default=is_default,
    )
    db.add(connection)
    await db.flush()
    await db.refresh(connection)
    return connection


async def update_connection(
    db: AsyncSession, *, connection: SandboxConnection, update_data: dict[str, Any]
) -> SandboxConnection:
    for field, value in update_data.items():
        setattr(connection, field, value)
    await db.flush()
    await db.refresh(connection)
    return connection


async def clear_default(
    db: AsyncSession, *, organization_id: UUID, except_id: UUID | None = None
) -> None:
    """Demote whichever connection is currently the default.

    One statement rather than a read-then-write per row: promoting a connection
    has to leave exactly one default behind, and a loop that fails in the middle
    leaves none or two.
    """
    statement = (
        update(SandboxConnection)
        .where(
            SandboxConnection.organization_id == organization_id,
            SandboxConnection.is_default.is_(True),
        )
        .values(is_default=False)
    )
    if except_id is not None:
        statement = statement.where(SandboxConnection.id != except_id)
    await db.execute(statement)


async def delete(db: AsyncSession, *, connection: SandboxConnection) -> None:
    await db.delete(connection)
    await db.flush()
