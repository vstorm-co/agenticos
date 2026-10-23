"""Binding an agent to this platform's own MCP server (#2063)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.spec import AgentSpec, OrgMcpServerRef, PlatformMcpServerRef
from app.core.permissions import AuthContext, Perm
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

    async def test_a_run_resumed_by_somebody_else_keeps_its_owner_s_authority(self) -> None:
        """Codex on #2062: an administrator answering an approval lent the run their role."""
        runner = AgentRunnerService(MagicMock())
        owner = uuid.uuid4()
        run = MagicMock(user_id=owner, initiated_by_publisher_fallback=False, key_scopes=None)
        membership = MagicMock(role="member")

        with patch(
            "app.services.agent_runner.member_repo.get_active",
            new=AsyncMock(return_value=membership),
        ):
            rebuilt = await runner._run_owner_context(CTX, run)
        assert rebuilt is not None
        assert (rebuilt.user_id, rebuilt.role) == (owner, "member")

        bound = AgentSpec(
            name="AI Architect", mcp_servers=[PlatformMcpServerRef(account="platform")]
        )
        with (
            patch(
                "app.services.agent_runner.member_repo.get_active",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.agent_runner.mint_for_run", new=AsyncMock()) as mint,
        ):
            assert await runner._run_owner_context(CTX, run) is None
            assert await runner._platform_credential(bound, CTX, run) is None
        mint.assert_not_awaited()

        assert await runner._run_owner_context(CTX, None) is CTX
        own = MagicMock(user_id=CTX.user_id, key_scopes=None)
        assert await runner._run_owner_context(CTX, own) is CTX

    @pytest.mark.security
    async def test_a_run_a_key_started_stays_under_the_key_when_resumed(self) -> None:
        """Codex on #2062: an `agents:run` key's run, approved and resumed by
        somebody else, minted a credential with the owner's whole role."""
        runner = AgentRunnerService(MagicMock())
        owner = uuid.uuid4()
        run = MagicMock(
            user_id=owner, initiated_by_publisher_fallback=False, key_scopes=["agents:run", "nope"]
        )

        with patch(
            "app.services.agent_runner.member_repo.get_active",
            new=AsyncMock(return_value=MagicMock(role="owner")),
        ):
            rebuilt = await runner._run_owner_context(CTX, run)
        assert rebuilt is not None
        assert rebuilt.key_scopes == frozenset({Perm.AGENTS_RUN})
        assert not rebuilt.has(Perm.MEMBERS_MANAGE)

        # The owner resuming it themselves stays under it too, and a key they
        # resume with narrows it further.
        mine = MagicMock(user_id=CTX.user_id, key_scopes=["agents:run", "agents:view"])
        resumed = await runner._run_owner_context(CTX, mine)
        assert resumed is not None
        assert resumed.key_scopes == frozenset({Perm.AGENTS_RUN, Perm.AGENTS_VIEW})
        keyed = AuthContext(
            user_id=CTX.user_id,
            organization_id=CTX.organization_id,
            role="owner",
            key_scopes=frozenset({Perm.AGENTS_VIEW}),
        )
        narrowed = await runner._run_owner_context(keyed, mine)
        assert narrowed is not None
        assert narrowed.key_scopes == frozenset({Perm.AGENTS_VIEW})


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
