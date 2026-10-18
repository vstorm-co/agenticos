"""Which agents use an MCP server, and what they asked it to do (#2072)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentStatus
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.services.mcp_connection import McpConnectionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_NOW = datetime.now(UTC)


async def _setup(db: AsyncSession) -> tuple[Organization, AuthContext]:
    owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization, AuthContext(
        user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER
    )


async def _server(db: AsyncSession, organization: Organization, name: str) -> McpConnection:
    connection = McpConnection(
        scope="org",
        organization_id=organization.id,
        name=name,
        url="https://mcp.example.com/mcp",
        secret_key_version=1,
    )
    db.add(connection)
    await db.flush()
    return connection


async def _agent(
    db: AsyncSession,
    organization: Organization,
    name: str,
    servers: object,
    *,
    status: AgentStatus = AgentStatus.DRAFT,
    visibility: Visibility = Visibility.ORG,
) -> Agent:
    spec = AgentSpec(name=name).model_dump(mode="json") | {"mcp_servers": servers}
    agent = Agent(
        organization_id=organization.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
        draft_spec=spec,
        status=status.value,
        visibility=visibility.value,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _called(
    db: AsyncSession,
    organization: Organization,
    agent: Agent | None,
    tool: str,
    ago: int,
    *,
    served_by: McpConnection | None = None,
) -> None:
    conversation = Conversation(organization_id=organization.id)
    db.add(conversation)
    await db.flush()
    message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="ok",
        agent_id=agent.id if agent else None,
    )
    db.add(message)
    await db.flush()
    db.add(
        ToolCall(
            message_id=message.id,
            tool_call_id=uuid.uuid4().hex,
            tool_name=tool,
            args={"query": "salaries"},
            result="secret",
            status="completed",
            started_at=_NOW - timedelta(minutes=ago),
            duration_ms=120,
            mcp_connection_id=served_by.id if served_by else None,
        )
    )
    await db.flush()


class TestWhoUsesAServer:
    async def test_the_live_agents_binding_it_that_the_reader_may_see(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _setup(db)
        notion = await _server(db, organization, "notion")
        linear = await _server(db, organization, "linear")
        bound = {"account": "organization", "connection_id": str(notion.id)}
        await _agent(db, organization, "Writer", [bound])
        await _agent(db, organization, "Archivist", [bound], status=AgentStatus.ARCHIVED)
        await _agent(db, organization, "Mine", [{"account": "personal", "catalog_key": "notion"}])
        await _agent(db, organization, "Broken", "not a list")

        used = await McpConnectionService(db).used_by(owner, [notion, linear])

        assert [agent.name for agent in used[notion.id]] == ["Writer"]
        assert used[linear.id] == []
        assert await McpConnectionService(db).used_by(owner, []) == {}


class TestWhatItWasAskedToDo:
    async def test_its_calls_newest_first_without_what_was_said(self, db: AsyncSession) -> None:
        organization, owner = await _setup(db)
        notion = await _server(db, organization, "notion-work")
        writer = await _agent(db, organization, "Writer", [])
        await _called(db, organization, writer, "notion_work_search", ago=5, served_by=notion)
        await _called(db, organization, None, "notion_work_create_page", ago=1, served_by=notion)
        other, _ = await _setup(db)
        await _called(db, other, None, "notion_work_search", ago=0, served_by=notion)

        calls = await McpConnectionService(db).recent_calls(owner, connection_id=notion.id)

        assert [(call.tool, call.agent_name) for call in calls] == [
            ("create_page", None),
            ("search", "Writer"),
        ]
        assert "args" not in calls[0].model_dump()
        assert "result" not in calls[0].model_dump()

    async def test_a_same_named_connection_and_unrecorded_calls_are_not_its_own(
        self, db: AsyncSession
    ) -> None:
        """A member's own Notion carries the server's prefix; neither its calls nor
        those written before the connection was recorded are this server's."""
        organization, owner = await _setup(db)
        notion = await _server(db, organization, "notion")
        await _called(db, organization, None, "notion_search", ago=3)
        await _called(db, organization, None, "notion_fetch", ago=2, served_by=notion)

        calls = await McpConnectionService(db).recent_calls(owner, connection_id=notion.id)

        assert [call.tool for call in calls] == ["fetch"]

    async def test_another_organizations_server_is_not_found(self, db: AsyncSession) -> None:
        organization, _owner = await _setup(db)
        theirs = await _server(db, organization, "notion")
        _other, stranger = await _setup(db)

        with pytest.raises(NotFoundError):
            await McpConnectionService(db).recent_calls(stranger, connection_id=theirs.id)
