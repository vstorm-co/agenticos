"""Binding an agent to this platform's own MCP server (#2063)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.spec import AgentSpec, OrgMcpServerRef, PlatformMcpServerRef
from app.core.permissions import AuthContext
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio

CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


class TestTheCredential:
    async def test_minted_only_for_an_agent_that_binds_the_platform(self) -> None:
        runner = AgentRunnerService(MagicMock())
        mint = AsyncMock(return_value="aos_minted")
        bound = AgentSpec(
            name="AI Architect", mcp_servers=[PlatformMcpServerRef(account="platform")]
        )
        unbound = AgentSpec(name="Support")

        with patch("app.services.agent_runner.mint_for_run", new=mint):
            assert await runner._platform_credential(bound, CTX) == "aos_minted"
            assert await runner._platform_credential(unbound, CTX) is None

        mint.assert_awaited_once_with(CTX)


class TestPublishing:
    async def test_the_platform_is_bound_under_its_own_prefix(self) -> None:
        registry = AgentRegistryService(MagicMock())
        connection = MagicMock(visibility="org")
        connection.name = "agenticos"
        org_ref = OrgMcpServerRef(connection_id=uuid.uuid4())

        with patch(
            "app.services.agent_registry.mcp_connection_repo.get_org_scoped_by_ids",
            new=AsyncMock(return_value={org_ref.connection_id: connection}),
        ):
            alone = await registry._mcp_problems(CTX, [PlatformMcpServerRef(account="platform")])
            clashing = await registry._mcp_problems(
                CTX, [PlatformMcpServerRef(account="platform"), org_ref]
            )

        assert alone == []
        assert len(clashing) == 1
        assert "'agenticos'" in clashing[0]
