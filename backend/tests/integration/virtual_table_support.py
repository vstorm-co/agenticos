"""Seed helpers shared by the Virtual Tables integration tests."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTable, VirtualTableRecord
from app.schemas.table_view import TableViewConfig, TableViewCreate, ViewVisibility
from app.schemas.virtual_table import (
    ColumnDef,
    ColumnInput,
    ColumnTypeName,
    OptionInput,
    RecordRead,
    TableCreate,
    TableRead,
)
from app.services.virtual_tables import BoundView, TableViewService, VirtualTableService


async def make_user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def make_org(db: AsyncSession, *, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def make_table(
    db: AsyncSession, *, org: Organization, owner: User, name: str
) -> VirtualTable:
    table = VirtualTable(organization_id=org.id, owner_user_id=owner.id, name=name)
    db.add(table)
    await db.flush()
    return table


def ctx_for(user: User, org: Organization, role: str = "owner") -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=role)


def column(label: str, type_: ColumnTypeName, **rest: Any) -> ColumnInput:
    return ColumnInput(label=label, type=type_, **rest)


async def orders_table(
    service: VirtualTableService, ctx: AuthContext, name: str = "Orders"
) -> TableRead:
    """A table with one column of most types, for tests that need cells to work with."""
    return await service.create_table(
        ctx,
        TableCreate(
            name=name,
            columns=[
                column("Customer", "text"),
                column("Quantity", "integer"),
                column("Total", "number"),
                column("Paid", "boolean"),
                column("Due", "date"),
                column("Placed", "datetime"),
                column(
                    "Status",
                    "single_select",
                    options=[OptionInput(label="Open"), OptionInput(label="Shipped")],
                ),
                column(
                    "Tags",
                    "multi_select",
                    options=[OptionInput(label="Rush"), OptionInput(label="Gift")],
                ),
            ],
        ),
    )


def cid(table: TableRead, label: str) -> str:
    """The id of the column with this label, as a record's `values` key."""
    return str(next(item.id for item in table.columns if item.label == label))


async def insert_rows(
    db: AsyncSession,
    table: TableRead,
    rows: list[dict[str, Any]],
    *,
    external_ids: list[str | None] | None = None,
) -> list[uuid.UUID]:
    """Records written straight to the table, one microsecond apart, in this order.

    Skips the service's checks and its history, so a test can seed a thousand rows
    quickly or a cell past its column's limit. Their ids, in `created_at` order.
    """
    organization_id = (
        await db.execute(select(VirtualTable.organization_id).where(VirtualTable.id == table.id))
    ).scalar_one()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    ids = [uuid.uuid4() for _ in rows]
    await db.execute(
        insert(VirtualTableRecord),
        [
            {
                "id": record_id,
                "organization_id": organization_id,
                "table_id": table.id,
                "external_id": None if external_ids is None else external_ids[index],
                "schema_version": table.schema_version,
                "values": values,
                "revision": 1,
                "created_at": start + timedelta(microseconds=index),
            }
            for index, (record_id, values) in enumerate(zip(ids, rows, strict=True))
        ],
    )
    return ids


async def bound_view(
    db: AsyncSession,
    ctx: AuthContext,
    table_id: uuid.UUID,
    config: TableViewConfig | None = None,
    *,
    visibility: ViewVisibility = "private",
) -> BoundView:
    """A new view of the table, found again as a page binding finds it."""
    views = TableViewService(db)
    view = await views.create_view(
        ctx,
        table_id,
        TableViewCreate(
            name=f"View {uuid.uuid4().hex[:6]}",
            kind="table",
            visibility=visibility,
            config=config or TableViewConfig(),
        ),
    )
    return await views.find_view(ctx, view.id)


def shaper(
    columns: Sequence[ColumnDef], named: Sequence[uuid.UUID]
) -> Callable[[RecordRead], dict[str, Any]]:
    """A page's shape for these columns: the id, then each named cell by its label.

    A choice reads as its label and a link as `[{id, label}]`, `[]` when the
    reader may not see the linked table.
    """
    by_id = {item.id: item for item in columns}

    def shape(record: RecordRead) -> dict[str, Any]:
        shaped: dict[str, Any] = {"id": str(record.id)}
        for column_id in named:
            column_def = by_id[column_id]
            key = str(column_id)
            value = record.values.get(key)
            if column_def.type == "link":
                value = [
                    {"id": str(linked.id), "label": linked.label}
                    for linked in record.links.get(key, [])
                ]
            elif column_def.options and isinstance(value, str):
                labels = {str(option.id): option.label for option in column_def.options}
                value = labels.get(value, value)
            shaped[column_def.label] = value
        return shaped

    return shape


def shaped_size(record: dict[str, Any]) -> int:
    return len(json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode())
