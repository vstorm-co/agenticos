"""What a workflow editor may pick: the organization's own servers, and only those."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.mcp_connection import McpConnectionService

pytestmark = pytest.mark.anyio


async def _organization(db: AsyncSession) -> tuple[Organization, User]:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role="member"))
    await db.flush()
    return organization, user


def _server(organization: Organization, name: str, **overrides: object) -> McpConnection:
    fields: dict[str, object] = {
        "organization_id": organization.id,
        "scope": "org",
        "purpose": "mcp",
        "name": name,
        "url": f"https://{name}.example/mcp",
    }
    fields.update(overrides)
    return McpConnection(**fields)


async def test_only_the_callers_organization_servers_are_listed(db: AsyncSession) -> None:
    organization, user = await _organization(db)
    other, _ = await _organization(db)
    db.add_all(
        [
            _server(organization, "wiki"),
            # Another tenant's, a person's own, and a portal grant: none are an
            # organization server a workflow step may bind.
            _server(other, "theirs"),
            _server(organization, "mine", scope="user", organization_id=None, user_id=user.id),
            _server(
                organization,
                "portal",
                purpose="portal",
                portal_key="github",
                created_by_user_id=user.id,
            ),
        ]
    )
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=organization.id, role="member")

    rows = await McpConnectionService(db).list_usable(ctx)

    assert [row.name for row in rows] == ["wiki"]
