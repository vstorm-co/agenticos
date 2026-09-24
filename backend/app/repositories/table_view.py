"""Table Views repository (PostgreSQL async). Pure data access, one table."""

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.table_view import TableView


async def get(db: AsyncSession, *, organization_id: UUID, view_id: UUID) -> TableView | None:
    result = await db.execute(
        select(TableView).where(
            TableView.id == view_id, TableView.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(
    db: AsyncSession, *, organization_id: UUID, table_id: UUID, owner_user_id: UUID, name: str
) -> TableView | None:
    result = await db.execute(
        select(TableView).where(
            TableView.organization_id == organization_id,
            TableView.table_id == table_id,
            TableView.owner_user_id == owner_user_id,
            TableView.name == name,
        )
    )
    return result.scalar_one_or_none()


def _visible(
    *, organization_id: UUID, table_id: UUID, user_id: UUID, kind: str | None
) -> list[ColumnElement[bool]]:
    where = [
        TableView.organization_id == organization_id,
        TableView.table_id == table_id,
        or_(TableView.owner_user_id == user_id, TableView.visibility == "shared"),
    ]
    if kind is not None:
        where.append(TableView.kind == kind)
    return where


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    user_id: UUID,
    kind: str | None = None,
    skip: int = 0,
    limit: int | None = None,
) -> list[TableView]:
    """The user's own views plus every view shared under this table, theirs first.

    `limit=None` reads them all, for a caller that must see every one - the
    dependency checker.
    """
    where = _visible(organization_id=organization_id, table_id=table_id, user_id=user_id, kind=kind)
    result = await db.execute(
        select(TableView)
        .where(*where)
        .order_by((TableView.owner_user_id != user_id), TableView.name.asc(), TableView.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    user_id: UUID,
    kind: str | None = None,
) -> int:
    """How many views `list_visible` would return across every page."""
    where = _visible(organization_id=organization_id, table_id=table_id, user_id=user_id, kind=kind)
    result = await db.execute(select(func.count()).select_from(TableView).where(*where))
    return result.scalar_one()


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    owner_user_id: UUID,
    name: str,
    kind: str,
    visibility: str,
    config: dict[str, Any],
) -> TableView:
    view = TableView(
        organization_id=organization_id,
        table_id=table_id,
        owner_user_id=owner_user_id,
        name=name,
        kind=kind,
        visibility=visibility,
        config=config,
    )
    db.add(view)
    await db.flush()
    await db.refresh(view)
    return view


async def update(db: AsyncSession, *, view: TableView, update_data: dict[str, Any]) -> TableView:
    for field, value in update_data.items():
        setattr(view, field, value)
    await db.flush()
    await db.refresh(view)
    return view


async def delete(db: AsyncSession, *, view: TableView) -> None:
    await db.delete(view)
    await db.flush()
