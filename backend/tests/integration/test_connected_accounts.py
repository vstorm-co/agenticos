"""Connected accounts against a real database (#2191).

The two reads a run and the vault page rest on: a person's accounts are theirs
alone and an organization's its own, and a row still waiting at the consent screen
is not an account yet. Also that the purpose the migration admits is one the table
accepts - and that an MCP read never offers an account as a server.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import mcp_connection_repo

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession, owner: User) -> Organization:
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    return organization


async def test_each_owner_reads_only_their_own_consented_accounts(db: AsyncSession) -> None:
    ana, ben = await _person(db), await _person(db)
    acme = await _organization(db, ana)
    anas = await mcp_connection_repo.create(
        db,
        user_id=ana.id,
        name="google:ana@acme.com",
        url="https://www.googleapis.com",
        auth_token=None,
        secret_key_version=1,
        allowed_tools=None,
        auth_type="oauth",
        oauth_payload="sealed",
        catalog_key="google",
        purpose="account",
    )
    await mcp_connection_repo.create(
        db,
        user_id=ana.id,
        name="google-account-pending",
        url="https://www.googleapis.com",
        auth_token=None,
        secret_key_version=1,
        allowed_tools=None,
        auth_type="oauth",
        oauth_pending_payload="pending",
        catalog_key="google",
        purpose="account",
    )
    await mcp_connection_repo.create(
        db,
        user_id=ben.id,
        name="google:ben@acme.com",
        url="https://www.googleapis.com",
        auth_token=None,
        secret_key_version=1,
        allowed_tools=None,
        oauth_payload="sealed",
        catalog_key="google",
        purpose="account",
    )
    acmes = await mcp_connection_repo.create_org_scoped(
        db,
        organization_id=acme.id,
        created_by_user_id=ana.id,
        name="google:ops@acme.com",
        url="https://www.googleapis.com",
        sealed_token=None,
        secret_key_version=1,
        allowed_tools=None,
        catalog_key="google",
        purpose="account",
    )
    await mcp_connection_repo.update(
        db, db_connection=acmes, update_data={"oauth_payload": "sealed"}
    )

    assert [
        row.id
        for row in await mcp_connection_repo.list_accounts(db, provider="google", user_id=ana.id)
    ] == [anas.id]
    assert [
        row.id
        for row in await mcp_connection_repo.list_accounts(
            db, provider="google", organization_id=acme.id
        )
    ] == [acmes.id]
    assert await mcp_connection_repo.list_accounts(db, provider="microsoft", user_id=ana.id) == []

    assert (await mcp_connection_repo.get_account(db, anas.id)) is not None
    server = McpConnection(
        user_id=ana.id,
        name="notion",
        url="https://mcp.notion.com",
        secret_key_version=1,
        purpose="mcp",
    )
    db.add(server)
    await db.flush()
    assert await mcp_connection_repo.get_account(db, server.id) is None

    # An MCP read never offers an account as a server to bind.
    servers, _ = await mcp_connection_repo.list_for_user(db, user_id=ana.id)
    assert [row.id for row in servers] == [server.id]
