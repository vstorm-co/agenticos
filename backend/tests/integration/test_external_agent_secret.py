"""A remote agent's registration goes with the key it was registered with.

Left behind with no key, the registration reads as one that never asked for
one, and its next call goes out unauthenticated - perhaps to an endpoint that
answers anonymous requests under another identity. Only the database's foreign
key decides this, so only a real database can show it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.db.models.external_agent import ExternalAgent
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import external_agent_repo, organization_secret_repo
from app.services.organization_secret import OrganizationSecretService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_deleting_the_key_deletes_the_registration(db) -> None:
    owner = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(owner)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    secret = await OrganizationSecretService(db).create(
        ctx, name="Reviewer key", value=ApiKeySecret(api_key="sk-remote-4242"), purpose="a2a"
    )
    await external_agent_repo.create(
        db,
        organization_id=organization.id,
        slug="reviewer",
        name="Reviewer",
        description="",
        card_url="https://agents.example.com/card.json",
        endpoint_url="https://agents.example.com/a2a",
        card={},
        secret_id=secret.id,
        created_by_user_id=owner.id,
    )

    organization_id = organization.id
    await organization_secret_repo.delete(db, secret.id, organization_id=organization_id)
    db.expire_all()

    left = await db.execute(
        select(ExternalAgent.id).where(ExternalAgent.organization_id == organization_id)
    )
    assert left.scalars().all() == []
