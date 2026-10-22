"""An MCP server's outage against a real database: opened once, closed once, said once (#2100).

The unit tests read the statements back; these are the half only Postgres can
answer - that the conditional writes really leave one caller holding the
outage, and that a server failing check after check writes one notification
per recipient rather than one per check.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, OrgMcpServerRef
from app.db.models.agent import Agent
from app.db.models.mcp_connection import McpConnection
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import mcp_connection_repo
from app.services.mcp_connection import record_reachability

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _server_with_an_agent(db: AsyncSession) -> tuple[McpConnection, User, User]:
    """An organization server, its owner-administrator, and a member whose agent binds it."""
    owner, builder = await _person(db), await _person(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"),
            OrganizationMember(organization_id=organization.id, user_id=builder.id, role="builder"),
        ]
    )
    server = McpConnection(
        organization_id=organization.id,
        scope="org",
        name="linear",
        url="https://mcp.linear.app/mcp",
        created_by_user_id=owner.id,
    )
    db.add(server)
    await db.flush()
    db.add(
        Agent(
            organization_id=organization.id,
            owner_user_id=builder.id,
            name="Triage",
            slug=f"triage-{uuid.uuid4().hex[:8]}",
            draft_spec=AgentSpec(
                name="Triage", mcp_servers=[OrgMcpServerRef(connection_id=server.id)]
            ).model_dump(mode="json"),
            visibility=Visibility.ORG.value,
        )
    )
    await db.flush()
    return server, owner, builder


async def _said(db: AsyncSession, event_type: NotificationEventType) -> list[uuid.UUID]:
    rows = await db.execute(
        select(Notification.recipient_user_id).where(Notification.event_type == event_type.value)
    )
    return sorted(rows.scalars().all())


async def test_only_the_first_check_opens_an_outage_and_only_one_closes_it(db: AsyncSession):
    server, _, _ = await _server_with_an_agent(db)
    began = datetime.now(UTC)

    assert await mcp_connection_repo.open_outage(db, connection=server, at=began)
    assert not await mcp_connection_repo.open_outage(
        db, connection=server, at=began + timedelta(minutes=15)
    )
    assert server.unreachable_since == began

    assert await mcp_connection_repo.close_outage(db, connection=server) == began
    assert await mcp_connection_repo.close_outage(db, connection=server) is None
    assert server.unreachable_since is None


async def test_a_day_of_failed_checks_is_one_notice_each_way(db: AsyncSession):
    """The administrators and the bound agent's owner, once down, once back - and
    a second outage is a second notice, not a duplicate of the first."""
    server, owner, builder = await _server_with_an_agent(db)
    audience = sorted([owner.id, builder.id])

    for _ in range(3):
        await record_reachability(db, server, reachable=False)
    await record_reachability(db, server, reachable=True)
    await record_reachability(db, server, reachable=True)

    assert await _said(db, NotificationEventType.MCP_SERVER_DOWN) == audience
    assert await _said(db, NotificationEventType.MCP_SERVER_RECOVERED) == audience

    await record_reachability(db, server, reachable=False)

    assert await _said(db, NotificationEventType.MCP_SERVER_DOWN) == sorted(audience * 2)
