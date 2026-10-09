"""The `platform` capability: the assistant's tools are the MCP server's, as the caller (#1798)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.agents.capabilities._registry import CapabilityBuildContext, get, load_builtins
from app.agents.capabilities.platform import (
    PLATFORM_CAPABILITY_ID,
    PLATFORM_CREDENTIAL_RESOURCE,
    PlatformOperations,
)
from app.agents.capabilities.platform import _toolset as toolset_module
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext, OrgRoleName

pytestmark = pytest.mark.anyio


def _build(resources: dict[str, Any]) -> PlatformOperations | None:
    load_builtins()
    definition = get(PLATFORM_CAPABILITY_ID)
    binding = MagicMock(capability_id=PLATFORM_CAPABILITY_ID, config={})
    return definition.builder(
        CapabilityBuildContext(binding=binding, config=None, resources=resources)
    )


class TestBuilding:
    def test_nobody_to_act_for_builds_nothing(self) -> None:
        assert _build({}) is None

    @pytest.mark.security
    def test_writes_are_declared_so_the_approval_gate_holds_them(self) -> None:
        load_builtins()
        tools = {tool.id: tool.side_effecting for tool in get(PLATFORM_CAPABILITY_ID).tools}

        assert tools["create_agent_draft"] is True
        assert tools["invite_member"] is True
        assert tools["list_agents"] is False

    def test_the_tools_are_the_mcp_server_s_and_built_once(self) -> None:
        built = _build({PLATFORM_CREDENTIAL_RESOURCE: SecretStr("aos_0123abcdsecret")})
        assert built is not None

        toolset = built.get_toolset()

        assert toolset is built.get_toolset()
        assert {"whoami", "create_agent_draft", "invite_member"} <= set(toolset.tools)
        assert "aos_0123abcdsecret" not in repr(built)


class TestCalling:
    async def test_a_call_goes_to_the_public_api_as_the_caller_and_a_refusal_is_the_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        async def refuse(request: Request) -> JSONResponse:
            seen.append(request.headers["authorization"])
            return JSONResponse(
                {"error": {"code": "AUTHORIZATION_ERROR", "message": "Insufficient permissions"}},
                status_code=403,
            )

        api = Starlette(routes=[Route("/api/v1/agents", refuse, methods=["POST"])])
        monkeypatch.setattr(toolset_module, "_api_app", lambda: api)
        built = _build({PLATFORM_CREDENTIAL_RESOURCE: SecretStr("aos_0123abcdsecret")})
        assert built is not None

        tool = built.get_toolset().tools["create_agent_draft"]
        answer = await tool.function(name="Bot", instructions="Be brief.")

        assert answer == {"refused": "403 AUTHORIZATION_ERROR: Insufficient permissions"}
        assert seen == ["Bearer aos_0123abcdsecret"]

    def test_the_api_is_the_application_itself(self) -> None:
        from app.main import app

        assert toolset_module._api_app() is app


class TestTheRunnerMintsOnlyWhenBound:
    def _spec(self, *bound: str) -> AgentSpec:
        return AgentSpec(
            name="Assistant",
            capabilities=[CapabilityBindingSpec(id=capability) for capability in bound],
        )

    async def test_a_credential_is_minted_for_an_agent_that_binds_the_capability(self) -> None:
        from app.services.agent_runner import AgentRunnerService

        runner = AgentRunnerService(MagicMock())
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER
        )
        with patch.object(
            runner.api_keys, "issue_for_run", new=AsyncMock(return_value="aos_x")
        ) as mint:
            bound = await runner._platform_resources(self._spec(PLATFORM_CAPABILITY_ID), ctx)
            unbound = await runner._platform_resources(self._spec("clock"), ctx)

        assert bound[PLATFORM_CREDENTIAL_RESOURCE].get_secret_value() == "aos_x"
        assert unbound == {}
        mint.assert_awaited_once_with(ctx)

    async def test_nothing_is_lent_when_nobody_is_behind_the_run(self) -> None:
        from app.services.agent_runner import AgentRunnerService

        runner = AgentRunnerService(MagicMock())
        ctx = AuthContext.anonymous(uuid.uuid4())
        with patch.object(runner.api_keys, "issue_for_run", new=AsyncMock(return_value=None)):
            assert await runner._platform_resources(self._spec(PLATFORM_CAPABILITY_ID), ctx) == {}
