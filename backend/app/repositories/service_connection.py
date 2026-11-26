"""Data access for service connections."""

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.service_connection import ServiceConnection


def _visible_to(organization_id: UUID | None):
    """The rows one organization may name: its own, and the deployment's.

    `None` is a caller with no organization - an app-scoped collection - which
    sees the deployment's rows and nobody else's.
    """
    if organization_id is None:
        return ServiceConnection.organization_id.is_(None)
    return or_(
        ServiceConnection.organization_id == organization_id,
        ServiceConnection.organization_id.is_(None),
    )


async def get_visible(
    db: AsyncSession, service_id: UUID, *, organization_id: UUID | None
) -> ServiceConnection | None:
    """One service, if this organization may name it.

    The scope is not decoration: without it a service id from another tenant
    resolves, and what it resolves to is a host somebody else's documents would
    be sent to.
    """
    result = await db.execute(
        select(ServiceConnection).where(
            ServiceConnection.id == service_id, _visible_to(organization_id)
        )
    )
    return result.scalar_one_or_none()


async def list_visible(
    db: AsyncSession, *, organization_id: UUID | None
) -> list[ServiceConnection]:
    result = await db.execute(
        select(ServiceConnection)
        .where(_visible_to(organization_id))
        .order_by(
            ServiceConnection.kind,
            ServiceConnection.organization_id.is_(None),
            ServiceConnection.name,
        )
    )
    return list(result.scalars().all())


async def get_by_name(
    db: AsyncSession, *, organization_id: UUID | None, kind: str, name: str
) -> ServiceConnection | None:
    """A row of this kind by name, within one owner - the organization's or the deployment's."""
    owner = (
        ServiceConnection.organization_id.is_(None)
        if organization_id is None
        else ServiceConnection.organization_id == organization_id
    )
    result = await db.execute(
        select(ServiceConnection).where(
            owner, ServiceConnection.kind == kind, ServiceConnection.name == name
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID | None,
    kind: str,
    provider: str,
    name: str,
    base_url: str,
    created_by_user_id: UUID | None,
    secret_id: UUID | None,
    requires_key: bool,
) -> ServiceConnection:
    row = ServiceConnection(
        organization_id=organization_id,
        kind=kind,
        provider=provider,
        name=name,
        base_url=base_url,
        created_by_user_id=created_by_user_id,
        secret_id=secret_id,
        requires_key=requires_key,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def update(
    db: AsyncSession, *, row: ServiceConnection, update_data: dict[str, Any]
) -> ServiceConnection:
    for field, value in update_data.items():
        setattr(row, field, value)
    await db.flush()
    await db.refresh(row)
    return row


async def delete(db: AsyncSession, *, row: ServiceConnection) -> None:
    await db.delete(row)
    await db.flush()
