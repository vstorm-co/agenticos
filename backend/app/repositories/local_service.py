"""Data access for local services."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.local_service import LocalService


def _visible_to(organization_id: UUID | None):
    """The rows one organization may name: its own, and the deployment's.

    `None` is a caller with no organization - an app-scoped collection - which
    sees the deployment's rows and nobody else's.
    """
    if organization_id is None:
        return LocalService.organization_id.is_(None)
    return or_(
        LocalService.organization_id == organization_id,
        LocalService.organization_id.is_(None),
    )


async def get_visible(
    db: AsyncSession, service_id: UUID, *, organization_id: UUID | None
) -> LocalService | None:
    """One service, if this organization may name it.

    The scope is not decoration: without it a service id from another tenant
    resolves, and what it resolves to is a host somebody else's documents would
    be sent to.
    """
    result = await db.execute(
        select(LocalService).where(LocalService.id == service_id, _visible_to(organization_id))
    )
    return result.scalar_one_or_none()


async def list_visible(db: AsyncSession, *, organization_id: UUID | None) -> list[LocalService]:
    result = await db.execute(
        select(LocalService)
        .where(_visible_to(organization_id))
        .order_by(LocalService.kind, LocalService.organization_id.is_(None), LocalService.name)
    )
    return list(result.scalars().all())


async def get_by_name(
    db: AsyncSession, *, organization_id: UUID | None, kind: str, name: str
) -> LocalService | None:
    """A row of this kind by name, within one owner - the organization's or the deployment's."""
    owner = (
        LocalService.organization_id.is_(None)
        if organization_id is None
        else LocalService.organization_id == organization_id
    )
    result = await db.execute(
        select(LocalService).where(owner, LocalService.kind == kind, LocalService.name == name)
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
) -> LocalService:
    row = LocalService(
        organization_id=organization_id,
        kind=kind,
        provider=provider,
        name=name,
        base_url=base_url,
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def update(
    db: AsyncSession, *, row: LocalService, update_data: dict[str, Any]
) -> LocalService:
    for field, value in update_data.items():
        setattr(row, field, value)
    await db.flush()
    await db.refresh(row)
    return row


async def delete(db: AsyncSession, *, row: LocalService) -> None:
    await db.delete(row)
    await db.flush()
