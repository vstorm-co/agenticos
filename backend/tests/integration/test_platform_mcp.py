"""The platform's MCP server, driven by a real MCP client against a real database (#2058).

Every tool is a public API call made with the caller's own token, so what is
asserted here is the join: the MCP handshake admits a key, the tools reach the
API as that key, and the key's narrowing and revocation hold through it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.schemas.api_key import ApiKeyCreate
from app.services.api_key import ApiKeyService
from app.services.platform_mcp import serve_platform_mcp

pytestmark = pytest.mark.anyio


@pytest.fixture
async def served(db: AsyncSession) -> AsyncIterator[None]:
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    async with serve_platform_mcp(app, app.state):
        yield
    app.dependency_overrides.clear()


async def _owner_key(db: AsyncSession, *scopes: Perm) -> tuple[str, Organization]:
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
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    created = await ApiKeyService(db).create(ctx, ApiKeyCreate(name="mcp", scopes=list(scopes)))
    # The token verifier opens a session of its own, so the key has to be visible
    # outside this test's transaction.
    await db.commit()
    return created.key, organization


@asynccontextmanager
async def _connected(key: str) -> AsyncIterator[ClientSession]:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {key}"},
    )
    async with (
        http,
        streamable_http_client("http://test/mcp", http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _content(result: Any) -> dict[str, Any]:
    return json.loads(result.content[0].text)


async def test_a_key_lists_the_tools_and_creates_an_agent_draft(
    db: AsyncSession, served: None
) -> None:
    key, organization = await _owner_key(db, Perm.AGENTS_VIEW, Perm.AGENTS_EDIT)

    async with _connected(key) as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        me = _content(await session.call_tool("whoami", {}))
        created = await session.call_tool(
            "create_agent", {"name": "Refunds", "instructions": "Answer refund questions."}
        )

    assert {"whoami", "create_agent", "invite_member", "search_knowledge"} <= tools
    assert me["organization_id"] == str(organization.id)
    assert not created.is_error
    agents = (
        await db.execute(select(Agent).where(Agent.organization_id == organization.id))
    ).scalars()
    assert [agent.name for agent in agents] == ["Refunds"]


@pytest.mark.security
async def test_a_tool_the_key_was_not_issued_for_is_refused_with_the_reason(
    db: AsyncSession, served: None
) -> None:
    key, _organization = await _owner_key(db, Perm.AGENTS_VIEW)

    async with _connected(key) as session:
        refused = await session.call_tool(
            "create_agent", {"name": "Refunds", "instructions": "Answer refund questions."}
        )

    assert refused.is_error
    assert "403" in refused.content[0].text


@pytest.mark.security
async def test_no_key_and_a_wrong_key_get_no_session(served: None) -> None:
    for headers in ({}, {"Authorization": "Bearer aos_00000000nothing"}):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.post(
                "/mcp",
                headers={**headers, "Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        assert response.status_code == 401
        assert "resource_metadata" in response.headers["www-authenticate"]


async def test_the_server_answers_503_when_it_is_not_running() -> None:
    app.state.platform_mcp = None
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post("/mcp", json={})

    assert response.status_code == 503
