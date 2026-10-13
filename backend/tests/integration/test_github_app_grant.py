"""Finding whose GitHub App delivery this is, against Postgres (#1072).

The one read in the connection repository that is deliberately not scoped to an
organization: an App delivery arrives at a shared URL carrying an installation id
and nothing else, so the grant has to be found before there is a tenant to scope
to. That makes the query itself worth an integration test - a mocked session
would prove the mock.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import mcp_connection_repo

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _organization(db: AsyncSession) -> Organization:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    return organization


async def _grant(
    db: AsyncSession,
    organization: Organization,
    *,
    portal_key: str = "github_app",
    installation: str | None = "42",
) -> McpConnection:
    grant = McpConnection(
        organization_id=organization.id,
        name=f"github-{uuid.uuid4().hex[:8]}",
        url="https://api.githubcopilot.com/mcp/",
        scope="org",
        purpose="portal",
        portal_key=portal_key,
        portal_account_id=installation,
    )
    db.add(grant)
    await db.flush()
    return grant


async def test_a_grant_is_found_by_the_installation_it_is_on(db: AsyncSession):
    organization = await _organization(db)
    grant = await _grant(db, organization)

    found = await mcp_connection_repo.portal_grants_for_account(
        db, portal_key="github_app", portal_account_id="42"
    )

    assert [row.id for row in found] == [grant.id]


async def test_every_candidate_comes_back_not_the_first(db: AsyncSession):
    """Two organizations could hold grants the provider numbered the same, and
    answering one would hand it the other's deliveries. The signature settles it,
    and it cannot if the query has already chosen."""
    mine = await _organization(db)
    theirs = await _organization(db)
    await _grant(db, mine)
    await _grant(db, theirs)

    found = await mcp_connection_repo.portal_grants_for_account(
        db, portal_key="github_app", portal_account_id="42"
    )

    assert {row.organization_id for row in found} == {mine.id, theirs.id}


async def test_another_portals_grant_on_the_same_id_is_not_returned(db: AsyncSession):
    organization = await _organization(db)
    await _grant(db, organization, portal_key="google")

    found = await mcp_connection_repo.portal_grants_for_account(
        db, portal_key="github_app", portal_account_id="42"
    )

    assert found == []


async def test_an_installation_nobody_holds_returns_nothing(db: AsyncSession):
    organization = await _organization(db)
    await _grant(db, organization)

    found = await mcp_connection_repo.portal_grants_for_account(
        db, portal_key="github_app", portal_account_id="999"
    )

    assert found == []
