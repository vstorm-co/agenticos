"""Seed helpers shared by the Virtual Tables integration tests."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTable


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
