"""Explicit API delegation reaches personal MCP, not the rest of a person's state."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import InstructionPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import AuthorityChecked, McpServerSpec, ToolOrigins
from app.agents.spec import OrgMcpServerRef
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.api_key import ApiKey
from app.db.models.mcp_connection import McpConnection
from app.schemas.api_key import ApiKeyCreate
from app.services.agent_runner import AdmittedAs, _personal_mcp_check
from app.services.api_key import ApiKeyService
from app.services.mcp_connection import _delegated_source_check, build_toolsets_for_agent

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def caller() -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role="member",
        api_key_id=uuid.uuid4(),
        key_scopes=frozenset({Perm.AGENTS_RUN, Perm.MCP_PERSONAL_USE}),
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"api_key_id": None},
        {"user_id": None},
        {"key_scopes": None},
        {"key_scopes": frozenset({Perm.AGENTS_RUN})},
        {"key_scopes": frozenset({Perm.MCP_PERSONAL_USE})},
        {"key_internal": True},
        {"subject_is_publisher_fallback": True},
        {"routine_id": uuid.uuid4()},
        {"fired_as_creator": "schedule"},
        {"source_conversation_id": uuid.uuid4()},
        {"role": "viewer"},
    ],
)
def test_personal_mcp_is_not_implicitly_delegated(fields: dict[str, object]) -> None:
    assert not replace(caller(), **fields).may_delegate_personal_mcp


def test_only_the_explicit_external_credential_is_eligible() -> None:
    assert caller().may_delegate_personal_mcp


def test_old_parked_state_does_not_gain_mcp_authority() -> None:
    state = AdmittedAs.model_validate({"acts_for_sender": False})
    assert state.personal_mcp_key_id is None
    assert "personal_mcp_key_id" not in state.model_dump(mode="json")
    key_id = uuid.uuid4()
    state = AdmittedAs(personal_mcp_key_id=key_id)
    assert AdmittedAs.model_validate_json(state.model_dump_json()).personal_mcp_key_id == key_id


async def test_one_persons_key_cannot_be_used_for_another_persons_connections() -> None:
    ctx = caller()
    service = ApiKeyService(MagicMock())
    with (
        patch("app.services.api_key.api_key_repo.get", new=AsyncMock(return_value=MagicMock())),
        patch.object(service, "_caller", new=AsyncMock(return_value=MagicMock(context=ctx))),
    ):
        assert (
            await service.personal_mcp_context(
                ctx.api_key_id, organization_id=ctx.organization_id, user_id=ctx.user_id
            )
            == ctx
        )
        with pytest.raises(AuthorizationError):
            await service.personal_mcp_context(
                ctx.api_key_id, organization_id=ctx.organization_id, user_id=uuid.uuid4()
            )


@pytest.mark.parametrize(
    "overrides",
    [
        {"revoked_at": datetime.now(UTC)},
        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        {"internal": True},
        {"scopes": ["agents:run"]},
    ],
)
async def test_delegation_checks_the_live_key_instead_of_saved_scopes(
    overrides: dict[str, object],
) -> None:
    ctx = caller()
    key = ApiKey(
        id=ctx.api_key_id,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        name="test",
        prefix="aos_01234567",
        key_hash="0" * 64,
        scopes=["agents:run", "mcp:personal:use"],
        internal=False,
    )
    for name, value in overrides.items():
        setattr(key, name, value)
    with (
        patch("app.services.api_key.api_key_repo.get", new=AsyncMock(return_value=key)),
        patch(
            "app.services.api_key.member_repo.get_active",
            new=AsyncMock(return_value=MagicMock(role="member")),
        ),
        patch(
            "app.services.api_key.user_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock(is_active=True)),
        ),
        patch(
            "app.services.api_key.organization_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock()),
        ),
        pytest.raises((AuthorizationError, AuthenticationError)),
    ):
        await ApiKeyService(MagicMock()).personal_mcp_context(
            ctx.api_key_id, organization_id=ctx.organization_id, user_id=ctx.user_id
        )


async def test_cross_tenant_key_is_not_resolved() -> None:
    ctx = caller()
    get = AsyncMock(return_value=None)
    with (
        patch("app.services.api_key.api_key_repo.get", new=get),
        pytest.raises(AuthenticationError),
    ):
        await ApiKeyService(MagicMock()).personal_mcp_context(
            ctx.api_key_id, organization_id=uuid.uuid4(), user_id=ctx.user_id
        )


async def test_impersonation_cannot_issue_personal_mcp_delegation() -> None:
    ctx = caller()
    with (
        patch("app.services.api_key.current_impersonator", return_value=uuid.uuid4()),
        pytest.raises(AuthorizationError),
    ):
        await ApiKeyService(MagicMock()).create(
            ctx, ApiKeyCreate(name="delegated", scopes=[Perm.AGENTS_RUN, Perm.MCP_PERSONAL_USE])
        )


async def test_each_mcp_call_rechecks_authority_and_does_not_call_after_revocation() -> None:
    calls = []
    tools = FunctionToolset()

    @tools.tool
    def read_record(_ctx: RunContext[None]) -> str:
        calls.append("read")
        return "permitted record"

    check = AsyncMock()
    wrapped = AuthorityChecked(wrapped=tools, check=check)
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    tool = (await wrapped.get_tools(ctx))["read_record"]
    check.side_effect = [None, AuthenticationError(message="Revoked")]
    assert await wrapped.call_tool("read_record", {}, ctx, tool) == "permitted record"
    with pytest.raises(AuthenticationError):
        await wrapped.call_tool("read_record", {}, ctx, tool)
    assert calls == ["read"]


async def test_delegated_mcp_rechecks_agent_access_with_the_original_subject() -> None:
    ctx = caller()

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield MagicMock()

    agent_id = uuid.uuid4()
    with (
        patch("app.services.agent_runner.get_db_context", session),
        patch(
            "app.services.agent_runner.ApiKeyService.personal_mcp_context",
            new=AsyncMock(return_value=ctx),
        ) as personal,
        patch(
            "app.services.agent_runner.AgentRegistryService.get",
            new=AsyncMock(return_value=MagicMock(status="published")),
        ) as agent,
    ):
        await _personal_mcp_check(
            ctx.api_key_id,
            user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
        )()
    assert personal.await_args.kwargs == {
        "organization_id": ctx.organization_id,
        "user_id": ctx.user_id,
    }
    assert agent.await_args.args == (ctx, agent_id)
    assert agent.await_args.kwargs == {"perm": Perm.AGENTS_RUN}


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "disabled",
        "deleted",
        "purpose",
        "endpoint",
        "generation",
        "owner",
        "tenant",
        "allowlist",
        "instructions",
        "trust",
    ],
)
async def test_cached_mcp_tools_stop_after_account_revocation_or_narrowing(change: str) -> None:
    ctx = caller()
    connection = McpConnection(
        id=uuid.uuid4(),
        user_id=ctx.user_id,
        organization_id=None,
        scope="user",
        purpose="mcp",
        is_enabled=True,
        name="notion",
        url="https://example.com/mcp",
        authorization_generation=uuid.uuid4(),
        allowed_tools=None,
        include_instructions=True,
        trust_read_only_hints=True,
    )
    spec = McpServerSpec(
        name="notion",
        include_instructions=True,
        trust_read_only_hints=True,
        url=connection.url,
        source_connection_id=connection.id,
        authorization_generation=connection.authorization_generation,
    )
    calls: list[str] = []
    tools = FunctionToolset()

    @tools.tool
    def read_record(_ctx: RunContext[None]) -> str:
        calls.append("read")
        return "record"

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield MagicMock()

    wrapped = AuthorityChecked(
        wrapped=tools,
        check=_delegated_source_check(
            spec, organization_id=ctx.organization_id, user_id=ctx.user_id
        ),
    )
    run_ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    with (
        patch("app.services.mcp_connection.get_db_context", session),
        patch(
            "app.services.mcp_connection.mcp_connection_repo.get_by_id",
            new=AsyncMock(return_value=connection),
        ) as get,
    ):
        tool = (await wrapped.get_tools(run_ctx))["read_record"]
        assert await wrapped.call_tool("read_record", {}, run_ctx, tool) == "record"
        if change == "disabled":
            connection.is_enabled = False
        elif change == "deleted":
            get.return_value = None
        elif change == "purpose":
            connection.purpose = "account"
        elif change == "endpoint":
            connection.url = "https://other.example/mcp"
        elif change == "generation":
            connection.authorization_generation = uuid.uuid4()
        elif change == "owner":
            connection.user_id = uuid.uuid4()
        elif change == "tenant":
            connection.scope = "org"
            connection.organization_id = uuid.uuid4()
        elif change == "allowlist":
            connection.allowed_tools = ["another_tool"]
        elif change == "instructions":
            connection.include_instructions = False
        elif change == "trust":
            connection.trust_read_only_hints = False
        if change == "none":
            assert await wrapped.call_tool("read_record", {}, run_ctx, tool) == "record"
            assert calls == ["read", "read"]
        else:
            with pytest.raises(AuthorizationError, match=r"reconnect|Reconnect"):
                await wrapped.call_tool("read_record", {}, run_ctx, tool)
            assert calls == ["read"]


@pytest.mark.parametrize("environment", [False, True])
@pytest.mark.parametrize("changed", ["allowlist", "disabled", "deleted", "generation", "endpoint"])
@pytest.mark.parametrize("target", ["production", "test"])
async def test_external_runs_attach_live_account_checks_to_the_resolved_connection(
    environment: bool,
    changed: str,
    target: str,
) -> None:
    ctx = caller()
    connection = McpConnection(
        id=uuid.uuid4(),
        user_id=None,
        organization_id=ctx.organization_id,
        scope="org",
        purpose="mcp",
        is_enabled=True,
        name="company",
        url="https://example.com/mcp",
        auth_type="none",
        authorization_generation=uuid.uuid4(),
        allowed_tools=["read"],
    )
    test_connection = McpConnection(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        scope="org",
        purpose="mcp",
        is_enabled=True,
        name="test-company",
        url="https://test.example.com/mcp",
        auth_type="none",
        authorization_generation=uuid.uuid4(),
        allowed_tools=["read"],
    )
    found = {connection.id: connection, test_connection.id: test_connection}
    calls: list[str] = []
    tools = FunctionToolset()

    @tools.tool
    def read(_ctx: RunContext[None]) -> str:
        calls.append("read")
        return "organization account"

    async def probe(
        specs: list[McpServerSpec],
    ) -> list[tuple[McpServerSpec, FunctionToolset[object]]]:
        return [(spec, tools) for spec in specs]

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield MagicMock()

    with (
        patch(
            "app.services.mcp_connection.mcp_connection_repo.get_org_scoped_by_ids",
            new=AsyncMock(return_value=found),
        ),
        patch("app.services.mcp_connection.probe_toolsets", probe),
        patch("app.services.mcp_connection.get_db_context", session),
        patch(
            "app.services.mcp_connection.mcp_connection_repo.get_by_id",
            new=AsyncMock(side_effect=lambda db, identifier: found.get(identifier)),
        ),
    ):
        resolved = await build_toolsets_for_agent(
            MagicMock(),
            organization_id=ctx.organization_id,
            refs=[OrgMcpServerRef(connection_id=connection.id)],
            sender_user_id=ctx.user_id,
            recheck_sources=True,
            test_connections={connection.id: test_connection.id} if environment else None,
        )
        wrapped = resolved.toolsets[0]
        assert isinstance(wrapped, ToolOrigins)
        assert isinstance(wrapped.wrapped, AuthorityChecked)
        run_ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
        tool = (await wrapped.get_tools(run_ctx))["read"]
        assert await wrapped.call_tool("read", {}, run_ctx, tool) == "organization account"
        selected = test_connection if target == "test" else connection
        if changed == "allowlist":
            selected.allowed_tools = ["different_tool"]
        elif changed == "disabled":
            selected.is_enabled = False
        elif changed == "deleted":
            found.pop(selected.id)
        elif changed == "generation":
            selected.authorization_generation = uuid.uuid4()
        elif changed == "endpoint":
            selected.url = "https://replacement.example.com/mcp"
        if not environment and target == "test":
            assert await wrapped.call_tool("read", {}, run_ctx, tool) == "organization account"
            assert calls == ["read", "read"]
        else:
            with pytest.raises(AuthorizationError):
                await wrapped.call_tool("read", {}, run_ctx, tool)
            assert calls == ["read"]


@pytest.mark.parametrize("missing", [True, False])
async def test_external_environment_run_refuses_an_unavailable_production_ceiling(
    missing: bool,
) -> None:
    ctx = caller()
    production_id, test_id = uuid.uuid4(), uuid.uuid4()
    production = McpConnection(id=production_id, is_enabled=False)
    with (
        patch(
            "app.services.mcp_connection.mcp_connection_repo.get_org_scoped_by_ids",
            AsyncMock(return_value={} if missing else {production_id: production}),
        ),
        pytest.raises(AuthorizationError, match="production MCP account"),
    ):
        await build_toolsets_for_agent(
            MagicMock(),
            organization_id=ctx.organization_id,
            refs=[OrgMcpServerRef(connection_id=production_id)],
            test_connections={production_id: test_id},
            recheck_sources=True,
        )


@pytest.mark.parametrize("missing", [True, False])
async def test_external_environment_can_disable_a_binding_with_no_live_production_account(
    missing: bool,
) -> None:
    ctx = caller()
    production_id = uuid.uuid4()
    production = McpConnection(id=production_id, is_enabled=False)
    with (
        patch(
            "app.services.mcp_connection.mcp_connection_repo.get_org_scoped_by_ids",
            AsyncMock(return_value={} if missing else {production_id: production}),
        ),
        patch("app.services.mcp_connection.probe_toolsets", AsyncMock(return_value=[])),
    ):
        result = await build_toolsets_for_agent(
            MagicMock(),
            organization_id=ctx.organization_id,
            refs=[OrgMcpServerRef(connection_id=production_id)],
            test_connections={production_id: None},
            recheck_sources=True,
        )
    assert result.toolsets == []


@pytest.mark.parametrize("target", ["root", "delegate"])
@pytest.mark.parametrize("change", ["grant-revoked", "unpublished"])
async def test_personal_tool_guard_rechecks_discovered_access_as_the_original_key_owner(
    change: str,
    target: str,
) -> None:
    owner = caller()
    root_id, delegate_id = uuid.uuid4(), uuid.uuid4()
    changed = False

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield MagicMock()

    async def get(ctx: AuthContext, agent_id: uuid.UUID, *, perm: Perm) -> MagicMock:
        assert ctx == owner
        assert perm == Perm.AGENTS_RUN
        if agent_id == (root_id if target == "root" else delegate_id) and changed:
            if change == "grant-revoked":
                raise AuthorizationError(message="Delegate grant revoked")
            return MagicMock(status="archived")
        return MagicMock(status="published")

    with (
        patch("app.services.agent_runner.get_db_context", session),
        patch(
            "app.services.agent_runner.ApiKeyService.personal_mcp_context",
            AsyncMock(return_value=owner),
        ),
        patch("app.services.agent_runner.AgentRegistryService.get", AsyncMock(side_effect=get)),
    ):
        guard = _personal_mcp_check(
            owner.api_key_id,
            user_id=owner.user_id,
            organization_id=owner.organization_id,
            agent_id=root_id,
        )
        await guard(delegates=frozenset({delegate_id}))
        changed = True
        with pytest.raises(AuthorizationError):
            await guard(delegates=frozenset({delegate_id}))


@pytest.mark.parametrize("boundary", ["entry", "tools", "instructions"])
async def test_revocation_prevents_reconnection_and_discovery(boundary: str) -> None:
    tools = FunctionToolset(instructions="Trusted server instructions")
    check = AsyncMock(side_effect=AuthorizationError(message="Authority revoked"))
    wrapped = AuthorityChecked(wrapped=tools, check=check)
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    with (
        patch.object(FunctionToolset, "__aenter__", AsyncMock()) as enter,
        patch.object(FunctionToolset, "get_tools", AsyncMock()) as discover,
        patch.object(FunctionToolset, "get_instructions", AsyncMock()) as instructions,
        pytest.raises(AuthorizationError, match="Authority revoked"),
    ):
        if boundary == "entry":
            async with wrapped:
                pytest.fail("A revoked connection must never enter")
        elif boundary == "tools":
            await wrapped.get_tools(ctx)
        else:
            await wrapped.get_instructions(ctx)
    enter.assert_not_awaited()
    discover.assert_not_awaited()
    instructions.assert_not_awaited()


async def test_live_authority_allows_entry_discovery_and_instructions() -> None:
    tools = FunctionToolset(instructions="Current server instructions")
    check = AsyncMock()
    wrapped = AuthorityChecked(wrapped=tools, check=check)
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    async with wrapped as entered:
        assert entered is wrapped
        assert await wrapped.get_tools(ctx) == {}
        assert await wrapped.get_instructions(ctx) == [
            InstructionPart(content="Current server instructions")
        ]
    assert check.await_count == 3
