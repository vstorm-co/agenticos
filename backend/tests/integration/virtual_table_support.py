"""Seed helpers shared by the Virtual Tables integration tests."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTable
from app.schemas.virtual_table import (
    ColumnInput,
    ColumnTypeName,
    OptionInput,
    TableCreate,
    TableRead,
)
from app.services.virtual_tables import VirtualTableService


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
