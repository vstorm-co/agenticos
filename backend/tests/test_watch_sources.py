"""A selected watch cannot gain accounts, tools or attached sources through a new publication."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from app.agents.spec import (
    AgentSpec,
    CapabilityBindingSpec,
    CodeModeSpec,
    ExternalAgentRef,
    PersonalMcpServerRef,
    SubagentRef,
)
from app.agents.watch_sources import WatchReadReceipt, WatchSourceTools
from app.core.exceptions import AuthorizationError, BadRequestError
from app.db.models.mcp_connection import McpConnection
from app.services.mcp_connection import _own_specs
from app.services.watch_sources import (
    WATCH_MAX_STEPS,
    approve_sources,
    constrain_sources,
    source_identity,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _connection() -> McpConnection:
    return McpConnection(
        id=uuid4(),
        authorization_generation=uuid4(),
        user_id=uuid4(),
        scope="user",
        purpose="mcp",
        name="GitHub",
        catalog_key="github",
        url="https://mcp.example/github",
        allowed_tools=None,
        is_enabled=True,
    )


def _spec() -> AgentSpec:
    return AgentSpec(
        name="Monitor",
        instructions="The selected agent's own instructions.",
        model_profile_id=uuid4(),
        mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="github")],
        collection_ids=[uuid4()],
        context_ids=[uuid4()],
        skill_ids=[uuid4()],
        capabilities=[
            CapabilityBindingSpec(id=name)
            for name in (
                "knowledge",
                "context",
                "guardrails",
                "planning",
                "system_reminders",
                "web",
                "sandbox",
                "delegation",
                "skills",
                "memory",
                "tool_output_limits",
                "compaction",
            )
        ],
        subagents=[SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())],
        external_agents=[ExternalAgentRef(external_agent_id=uuid4())],
        code_mode=CodeModeSpec(enabled=True),
    )


def test_new_publications_keep_their_model_and_voice_but_cannot_widen_sources() -> None:
    original = _spec()
    approved = approve_sources(original, _connection())
    published = original.model_copy(
        update={
            "instructions": "A newly published instruction.",
            "model_profile_id": uuid4(),
            "collection_ids": [*original.collection_ids, uuid4()],
            "context_ids": [*original.context_ids, uuid4()],
            "mcp_servers": [
                *original.mcp_servers,
                PersonalMcpServerRef(account="personal", catalog_key="notion"),
            ],
        }
    )
    effective = constrain_sources(published, approved)
    assert effective.instructions == published.instructions
    assert effective.model_profile_id == published.model_profile_id
    assert effective.collection_ids == original.collection_ids
    assert effective.context_ids == original.context_ids
    assert effective.mcp_servers == original.mcp_servers
    assert effective.subagents == effective.external_agents == effective.skill_ids == []
    assert not effective.code_mode.enabled
    assert {binding.id for binding in effective.capabilities} == {
        "knowledge",
        "context",
        "guardrails",
        "planning",
        "system_reminders",
        "tool_output_limits",
        "compaction",
    }
    assert effective.max_steps == WATCH_MAX_STEPS


def test_removed_attached_sources_are_not_lent_from_an_old_approval() -> None:
    original = _spec()
    approved = approve_sources(original, _connection())
    effective = constrain_sources(
        original.model_copy(update={"collection_ids": [], "context_ids": []}), approved
    )
    assert effective.collection_ids == effective.context_ids == []


@pytest.mark.parametrize(
    ("agent_tools", "account_tools", "expected"),
    [
        (None, None, None),
        (None, ["get"], ("get",)),
        (["get"], None, ("get",)),
        (["get", "search"], ["search", "delete"], ("search",)),
    ],
)
def test_account_and_published_tool_limits_intersect(agent_tools, account_tools, expected) -> None:
    spec = _spec()
    spec.mcp_servers = [
        PersonalMcpServerRef(account="personal", catalog_key="github", allowed_tools=agent_tools)
    ]
    connection = _connection()
    connection.allowed_tools = account_tools
    approved = approve_sources(spec, connection)
    assert approved.allowed_tools == expected


def test_a_publication_cannot_restore_a_tool_that_the_watch_never_approved() -> None:
    spec, connection = _spec(), _connection()
    connection.allowed_tools = ["get"]
    approved = approve_sources(spec, connection)
    published = spec.model_copy(
        update={
            "mcp_servers": [
                PersonalMcpServerRef(
                    account="personal", catalog_key="github", allowed_tools=["get", "new_read"]
                )
            ]
        }
    )
    assert constrain_sources(published, approved).mcp_servers[0].allowed_tools == ["get"]
    published.mcp_servers[0].allowed_tools = ["new_read"]
    with pytest.raises(AuthorizationError, match="no longer has approved tools"):
        constrain_sources(published, approved)


def test_empty_or_missing_bindings_are_refused_instead_of_automatically_enabled() -> None:
    spec, connection = _spec(), _connection()
    connection.allowed_tools = []
    with pytest.raises(AuthorizationError, match="no allowed tools"):
        approve_sources(spec, connection)
    connection.catalog_key = None
    with pytest.raises(AuthorizationError, match="does not have a personal binding"):
        approve_sources(spec, connection)


@pytest.mark.parametrize("gate", ["source", "capability", "tool"])
def test_a_watch_does_not_waive_the_agents_required_read_approval(gate: str) -> None:
    spec = _spec()
    if gate == "source":
        spec.mcp_servers[0].approval = "all"
    elif gate == "capability":
        spec.capabilities[0].approval = "required"
    else:
        spec.capabilities[0].tool_approval = {"search_documents": "required"}
    with pytest.raises(AuthorizationError, match="interactive approval"):
        approve_sources(spec, _connection())


def test_approval_never_copies_a_url_or_credential_into_the_run_policy() -> None:
    connection = _connection()
    connection.url += "?key=private-token"
    approved = approve_sources(_spec(), connection)
    assert approved.endpoint_hash == hashlib.sha256(connection.url.encode()).hexdigest()
    assert "private-token" not in approved.model_dump_json()
    assert "https://" not in approved.model_dump_json()


async def test_unapproved_accounts_and_changed_endpoints_are_filtered_before_credentials() -> None:
    chosen, extra = _connection(), _connection()
    extra.user_id = chosen.user_id
    chosen.is_default = False
    extra.is_default = True
    ref = PersonalMcpServerRef(account="personal", catalog_key="github")
    approved = {chosen.id: source_identity(approve_sources(_spec(), chosen))}
    with (
        patch(
            "app.services.mcp_connection.mcp_connection_repo.list_user_scoped_by_catalog_key",
            new=AsyncMock(return_value=[extra, chosen]),
        ),
        patch(
            "app.services.mcp_connection.resolve_auth_headers", new=AsyncMock(return_value={})
        ) as auth,
    ):
        found = await _own_specs(
            MagicMock(), ref, user_id=chosen.user_id, approved_sources=approved
        )
        assert isinstance(found, list) and len(found) == 1
        assert found[0].spec.name == "github"
        auth.assert_awaited_once_with(chosen)
        auth.reset_mock()
        chosen.url = "https://a-different-source.example"
        assert (
            await _own_specs(MagicMock(), ref, user_id=chosen.user_id, approved_sources=approved)
            == "not_connected"
        )
        auth.assert_not_awaited()


def _ctx() -> RunContext[object]:
    return RunContext(deps=object(), model=TestModel(), usage=RunUsage())


async def test_only_read_tools_are_offered_and_a_successful_read_is_evidenced() -> None:
    async def read() -> str:
        return "no matching items"

    async def write() -> str:
        raise AssertionError("An external write must never execute")

    raw = FunctionToolset[object](
        tools=[
            Tool(read, name="read", metadata={"annotations": {"readOnlyHint": True}}),
            Tool(write, name="write", metadata={"annotations": {"readOnlyHint": False}}),
            Tool(write, name="unclassified"),
        ]
    )
    receipt = WatchReadReceipt()
    bounded = WatchSourceTools(raw, receipt=receipt)
    ctx = _ctx()
    tools = await bounded.get_tools(ctx)
    assert set(tools) == {"read"}
    assert await bounded.call_tool("read", {}, ctx, tools["read"]) == "no matching items"
    assert receipt.completed_calls == 1 and not receipt.failed_requests
    original = await raw.get_tools(ctx)
    with pytest.raises(AuthorizationError, match="cannot mutate"):
        await bounded.call_tool("write", {}, ctx, original["write"])


async def test_a_read_its_binding_asks_before_is_left_out_of_the_watch() -> None:
    """Nobody is there to answer a watch's check, so a read the agent asks before
    is not offered; the reads that run unasked still are (#2884)."""
    from app.agents.mcp import ApprovalMarked

    async def read() -> str:
        return "items"

    raw = FunctionToolset[object](
        tools=[
            Tool(read, name="search", metadata={"annotations": {"readOnlyHint": True}}),
            Tool(read, name="fetch", metadata={"annotations": {"readOnlyHint": True}}),
        ]
    )
    marked = ApprovalMarked(raw, policy="writes", tool_approval={"fetch": "required"})

    tools = await WatchSourceTools(marked, receipt=WatchReadReceipt()).get_tools(_ctx())

    assert set(tools) == {"search"}


async def test_a_source_with_no_read_only_tools_is_an_explicit_failure() -> None:
    async def write() -> None:
        return None

    bounded = WatchSourceTools(FunctionToolset[object](tools=[write]), receipt=WatchReadReceipt())
    with pytest.raises(BadRequestError, match="no available read-only tools"):
        await bounded.get_tools(_ctx())


async def test_an_unresolved_failed_read_cannot_be_hidden_by_a_different_successful_read() -> None:
    failing = True

    async def read(query: str) -> str:
        if failing and query == "needed":
            raise ModelRetry("Source read failed")
        return "items"

    raw = FunctionToolset[object](
        tools=[Tool(read, metadata={"annotations": {"readOnlyHint": True}})]
    )
    receipt = WatchReadReceipt()
    bounded = WatchSourceTools(raw, receipt=receipt)
    ctx = _ctx()
    tool = (await bounded.get_tools(ctx))["read"]
    with pytest.raises(ModelRetry):
        await bounded.call_tool("read", {"query": "needed"}, ctx, tool)
    await bounded.call_tool("read", {"query": "different"}, ctx, tool)
    assert receipt.failed_requests
    failing = False
    await bounded.call_tool("read", {"query": "needed"}, ctx, tool)
    assert not receipt.failed_requests and receipt.completed_calls == 2


async def test_reconsent_cannot_read_a_different_account_behind_the_same_connection() -> None:
    connection = _connection()
    approved = approve_sources(_spec(), connection)
    ref = PersonalMcpServerRef(account="personal", catalog_key="github")
    with (
        patch(
            "app.services.mcp_connection.mcp_connection_repo.list_user_scoped_by_catalog_key",
            new=AsyncMock(return_value=[connection]),
        ),
        patch(
            "app.services.mcp_connection.resolve_auth_headers", new=AsyncMock(return_value={})
        ) as auth,
    ):
        connection.authorization_generation = uuid4()
        assert (
            await _own_specs(
                MagicMock(),
                ref,
                user_id=connection.user_id,
                approved_sources={connection.id: source_identity(approved)},
            )
            == "not_connected"
        )
        auth.assert_not_awaited()


def test_a_legacy_policy_requires_source_review_instead_of_guessing_account_identity() -> None:
    approved = approve_sources(_spec(), _connection())
    legacy = approved.model_copy(update={"authorization_generation": None})
    with pytest.raises(AuthorizationError, match="Review this watch"):
        source_identity(legacy)


async def test_resumed_accounts_keep_their_original_alias_after_default_and_label_edits() -> None:
    from app.agents.mcp import McpSourceIdentity, tool_prefix

    chosen, work, new = _connection(), _connection(), _connection()
    work.user_id = new.user_id = chosen.user_id
    chosen.is_default, work.is_default = True, False
    chosen.label, work.label, new.label = "Private", "Work", "New"
    accounts = [chosen, work]
    ref = PersonalMcpServerRef(account="personal", catalog_key="github")
    with (
        patch(
            "app.services.mcp_connection.mcp_connection_repo.list_user_scoped_by_catalog_key",
            new=AsyncMock(side_effect=lambda *_args, **_kwargs: accounts),
        ),
        patch(
            "app.services.mcp_connection.resolve_auth_headers", new=AsyncMock(return_value={})
        ) as auth,
    ):
        first = await _own_specs(MagicMock(), ref, user_id=chosen.user_id)
        assert isinstance(first, list)
        admitted = {
            account.spec.source_connection_id: McpSourceIdentity(
                endpoint_hash=hashlib.sha256(account.spec.url.encode()).hexdigest(),
                authorization_generation=account.spec.authorization_generation,
                tool_prefix=tool_prefix(account.spec.name),
            )
            for account in first
            if account.spec.source_connection_id is not None
            and account.spec.authorization_generation is not None
        }
        chosen.is_default, work.is_default = False, True
        chosen.label = "Renamed"
        accounts.append(new)
        auth.reset_mock()
        resumed = await _own_specs(
            MagicMock(), ref, user_id=chosen.user_id, approved_sources=admitted
        )
        assert isinstance(resumed, list) and len(resumed) == 2
        assert {
            account.spec.source_connection_id: tool_prefix(account.spec.name) for account in resumed
        } == {identifier: source.tool_prefix for identifier, source in admitted.items()}
        assert auth.await_count == 2
        assert all(call.args[0].id != new.id for call in auth.await_args_list)


@pytest.mark.parametrize(("published", "effective"), [(None, 30), (5, 5), (80, 30)])
def test_a_check_is_bounded_whatever_the_agent_allows(published, effective) -> None:
    """An unbounded check of a Notion workspace ran 40 steps and cost $2."""
    original = _spec()
    approved = approve_sources(original, _connection())
    spec = original.model_copy(update={"max_steps": published})
    assert constrain_sources(spec, approved).max_steps == effective
