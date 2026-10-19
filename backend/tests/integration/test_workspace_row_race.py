"""Two first opens of one workspace key both get the row, neither a uniqueness error.

Two teammates the first to work in a project at once both find no row and both
insert one. Only the database's unique key settles which insert stands, so only
a real database shows the loser attaching to the winner's row.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_workspace as workspace_repo

pytestmark = pytest.mark.anyio


async def test_the_second_insert_of_a_key_returns_the_first_row(db) -> None:
    founder = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    key = f"race-{uuid.uuid4().hex[:16]}"

    first = await workspace_repo.create(
        db,
        organization_id=organization.id,
        agent_id=None,
        scope="project",
        scope_key=key,
        backend="state",
    )
    second = await workspace_repo.create(
        db,
        organization_id=organization.id,
        agent_id=None,
        scope="project",
        scope_key=key,
        backend="state",
    )

    assert second.id == first.id
