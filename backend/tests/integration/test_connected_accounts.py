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


async def test_long_account_identities_and_pending_rows_stay_outside_mcp(db: AsyncSession) -> None:
    user = await _person(db)
    organization = await _organization(db, user)
    email = "a" * 64 + "@workspace.example.com"
    account = McpConnection(
        organization_id=organization.id,
        created_by_user_id=user.id,
        scope="org",
        name="google-account-long",
        url="https://www.googleapis.com",
        purpose="account",
        catalog_key="google",
        label=email[:64],
        account_email=email,
        auth_type="oauth",
        secret_key_version=1,
        oauth_pending_payload="pending",
    )
    db.add(account)
    await db.flush()
    pending = await mcp_connection_repo.get_pending_account(
        db,
        provider="google",
        organization_id=organization.id,
    )
    assert pending is not None and pending.id == account.id and pending.account_email == email
    assert (
        await mcp_connection_repo.get_org_scoped_by_catalog_key(
            db,
            organization_id=organization.id,
            catalog_key="google",
        )
        is None
    )


@pytest.mark.parametrize("scope", ["user", "org"])
async def test_account_identity_is_unique_per_owner(db: AsyncSession, scope: str) -> None:
    from sqlalchemy.exc import IntegrityError

    user, other = await _person(db), await _person(db)
    organization = await _organization(db, user)
    other_organization = await _organization(db, other)

    def account(owner: uuid.UUID) -> McpConnection:
        return McpConnection(
            user_id=owner if scope == "user" else None,
            organization_id=owner if scope == "org" else None,
            created_by_user_id=user.id if scope == "org" else None,
            scope=scope,
            name=f"google-account-{uuid.uuid4().hex}",
            url="https://www.googleapis.com",
            purpose="account",
            catalog_key="google",
            account_email="same@example.com",
            auth_type="oauth",
            secret_key_version=1,
            oauth_payload="sealed",
        )

    owner = user.id if scope == "user" else organization.id
    other_owner = other.id if scope == "user" else other_organization.id
    db.add_all([account(owner), account(other_owner)])
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(account(owner))
            await db.flush()


@pytest.mark.security
async def test_same_person_can_connect_one_address_through_two_tenants(db: AsyncSession) -> None:
    from sqlalchemy import delete, select

    user = await _person(db)
    first, second = await _organization(db, user), await _organization(db, user)
    accounts = []
    for organization in (first, second):
        account = McpConnection(
            user_id=user.id,
            account_source_organization_id=organization.id,
            name=f"google:{organization.id}",
            url="https://www.googleapis.com",
            secret_key_version=1,
            purpose="account",
            catalog_key="google",
            account_email="same@example.com",
            oauth_payload="sealed credential must never be exported",
        )
        db.add(account)
        accounts.append(account)
    await db.flush()
    identifiers = [account.id for account in accounts]
    from app.services.personal_data import PersonalDataService

    export = await PersonalDataService(db).export(user.id, actor_user_id=user.id)
    assert {row.id for row in export.connected_accounts} == set(identifiers)
    assert {row.account_source_organization_id for row in export.connected_accounts} == {
        first.id,
        second.id,
    }
    assert "sealed credential" not in export.model_dump_json()
    assert "oauth_payload" not in export.model_dump_json()
    await db.execute(delete(Organization).where(Organization.id == first.id))
    remaining = list(
        (await db.scalars(select(McpConnection.id).where(McpConnection.id.in_(identifiers)))).all()
    )
    assert remaining == [identifiers[1]]


@pytest.mark.security
async def test_removing_and_reinviting_a_member_does_not_restore_google_grants(
    db: AsyncSession,
) -> None:
    from sqlalchemy import select

    from app.db.models.organization import OrganizationMember
    from app.services.member import end_membership

    user = await _person(db)
    first, second = await _organization(db, user), await _organization(db, user)
    member = OrganizationMember(organization_id=first.id, user_id=user.id, role="member")
    db.add(member)
    accounts = []
    for org, pending in ((first, False), (second, False), (first, True)):
        account = McpConnection(
            user_id=user.id,
            account_source_organization_id=org.id,
            name=f"google:{org.id}:{pending}",
            url="https://www.googleapis.com",
            secret_key_version=1,
            purpose="account",
            catalog_key="google",
            account_email=None if pending else "same@example.com",
            oauth_payload=None if pending else "sealed",
            oauth_pending_payload="pending" if pending else None,
        )
        db.add(account)
        accounts.append(account)
    await db.flush()
    identifiers = [row.id for row in accounts]
    await end_membership(db, member)
    db.add(OrganizationMember(organization_id=first.id, user_id=user.id, role="member"))
    await db.flush()
    remaining = list(
        await db.scalars(select(McpConnection.id).where(McpConnection.id.in_(identifiers)))
    )
    assert remaining == [identifiers[1]]


@pytest.mark.security
async def test_reconsented_account_is_fresh_in_an_existing_session(
    db: AsyncSession, engine
) -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    user = await _person(db)
    account = McpConnection(
        user_id=user.id,
        name="google:session",
        url="https://www.googleapis.com",
        purpose="account",
        catalog_key="google",
        account_email="session@example.com",
        secret_key_version=1,
        oauth_payload="first",
    )
    db.add(account)
    await db.commit()
    before = (await mcp_connection_repo.get_account(db, account.id)).authorization_generation
    generation = uuid.uuid4()
    async with async_sessionmaker(engine)() as other:
        await other.execute(
            update(McpConnection)
            .where(McpConnection.id == account.id)
            .values(authorization_generation=generation)
        )
        await other.commit()
    assert (
        await mcp_connection_repo.get_account(db, account.id)
    ).authorization_generation == generation
    assert generation != before
