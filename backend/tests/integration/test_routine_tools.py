"""A routine can narrow its agent's tool settings per tool, and never release one."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import load_builtins
from app.agents.mcp import MCP_ORIGIN, PLATFORM_TOOL, McpSourceIdentity, McpToolOrigin, tool_prefix
from app.agents.routine_actions import RoutineToolsOff
from app.agents.spec import (
    AgentSpec,
    CapabilityBindingSpec,
    OrgMcpServerRef,
    PersonalMcpServerRef,
    PlatformMcpServerRef,
)
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.routine_actions import RoutineActionKey, RoutinePlatformActionKey
from app.schemas.routine_tools import (
    RoutineCapabilityToolOption,
    RoutineCapabilityToolSetting,
    RoutineMcpToolKey,
    RoutineMcpToolOption,
    RoutineMcpToolSetting,
    RoutinePlatformToolOption,
    RoutinePlatformToolSetting,
    RoutineToolSettings,
)
from app.services.agent_trigger import AgentTriggerService
from app.services.routine_authority import RoutineAuthority
from app.services.routine_readiness import blockers
from app.services.routine_sources import read_policy
from app.services.routine_tools import (
    RoutineToolService,
    capability_tool_options,
    read_tool_settings,
    stricter,
    tool_settings_of,
)
from tests.routine_source_support import reviewed_sources

pytestmark = [pytest.mark.anyio, pytest.mark.security]

EXECUTE = RoutineCapabilityToolSetting(capability_id="sandbox", tool_id="execute", setting="off")


@dataclass
class World:
    ctx: AuthContext
    org: Organization
    agent: Agent
    version: AgentVersion
    trigger: AgentTrigger
    spec: AgentSpec


@pytest.fixture
async def world(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> World:
    load_builtins()
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(
        organization_id=org.id,
        owner_user_id=user.id,
        name="Worker",
        slug=f"worker-{uuid4()}",
        status="published",
    )
    db.add_all([OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"), agent])
    await db.flush()
    spec = AgentSpec(
        name="Worker",
        capabilities=[
            CapabilityBindingSpec(id="sandbox", tool_approval={"write_file": "required"}),
            CapabilityBindingSpec(id="web_search", enabled=False),
        ],
    )
    version = AgentVersion(
        agent_id=agent.id, organization_id=org.id, version=1, spec=spec.model_dump(mode="json")
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    trigger = AgentTrigger(
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        prompt="Report",
        interval_seconds=300,
        next_fire_at=datetime.now(UTC),
        action_mode="agent",
    )
    db.add(trigger)
    await db.flush()
    reviewed_sources(trigger, spec=spec, version_id=version.id)
    await db.flush()

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr("app.services.routine_authority.get_db_context", context)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)
    return World(ctx, org, agent, version, trigger, spec)


async def capture(db: AsyncSession, world: World) -> RoutineAuthority:
    authority = await RoutineAuthority.capture(
        db,
        replace(
            world.ctx,
            routine_id=world.trigger.id,
            subject_is_publisher_fallback=True,
            routine_source_policy_id=read_policy(world.trigger.approved_sources).id,
        ),
        agent_id=world.agent.id,
        version_id=world.version.id,
        run=None,
    )
    assert authority is not None
    return authority


def sandbox(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, capability_id="sandbox")


async def save(db: AsyncSession, world: World, *settings: object) -> None:
    await AgentTriggerService(db).set_tool_settings(
        world.ctx,
        world.agent.id,
        world.trigger.id,
        RoutineToolSettings.model_validate({"settings": [*settings]}),
    )


async def test_every_tool_is_listed_with_the_agents_setting_and_reads_included(
    db: AsyncSession, world: World
) -> None:
    options = await AgentTriggerService(db).tool_options(
        world.ctx, world.agent.id, world.trigger.id
    )
    by_tool = {
        item.tool_id: item
        for item in options.items
        if isinstance(item, RoutineCapabilityToolOption)
    }
    assert by_tool["read_file"].agent == "free" and not by_tool["read_file"].effect
    assert by_tool["execute"].agent == "free" and by_tool["execute"].effect
    assert by_tool["write_file"].agent == "ask"
    assert by_tool["execute"].capability_name == "Sandbox"
    assert all(item.setting is None for item in options.items)


async def test_saving_narrows_follows_the_agent_and_drops_standing_consent(
    db: AsyncSession, world: World
) -> None:
    world.trigger.action_mode = "per_tool"
    world.trigger.action_consents = [{"stale": True}]
    await save(
        db,
        world,
        EXECUTE.model_dump(),
        {"capability_id": "sandbox", "tool_id": "read_file", "setting": "ask"},
        # The agent already asks before it: nothing to keep.
        {"capability_id": "sandbox", "tool_id": "write_file", "setting": "ask"},
    )
    await db.refresh(world.trigger)
    assert world.trigger.action_mode == "agent"
    assert world.trigger.action_consents == []
    assert read_tool_settings(world.trigger.tool_settings) == {
        RoutineActionKey(capability_id="sandbox", tool_id="execute"): "off",
        RoutineActionKey(capability_id="sandbox", tool_id="read_file"): "ask",
    }
    options = await RoutineToolService(db).tools(world.ctx, world.trigger)
    shown = {item.tool_id: item.setting for item in options.items}
    assert shown["execute"] == "off" and shown["read_file"] == "ask"
    assert shown["write_file"] is None
    # An empty list follows the agent again.
    await save(db, world)
    await db.refresh(world.trigger)
    assert world.trigger.tool_settings == []


async def test_a_tool_the_version_does_not_offer_or_named_twice_is_refused(
    db: AsyncSession, world: World
) -> None:
    with pytest.raises(BadRequestError) as refused:
        await save(db, world, {"capability_id": "sandbox", "tool_id": "invented", "setting": "off"})
    assert refused.value.details == {"tools": ["invented"]}
    with pytest.raises(BadRequestError):
        await save(db, world, EXECUTE.model_dump(), {**EXECUTE.model_dump(), "setting": "ask"})
    assert world.trigger.tool_settings == []


async def test_only_the_owner_in_the_console_can_narrow(db: AsyncSession, world: World) -> None:
    service = RoutineToolService(db)
    with pytest.raises(AuthorizationError):
        await service.tool_options(replace(world.ctx, api_key_id=uuid4()), world.trigger)
    with pytest.raises(AuthorizationError):
        await service.replace_settings(
            replace(world.ctx, user_id=uuid4()), world.trigger, RoutineToolSettings()
        )


async def test_a_routine_that_is_gone_cannot_be_narrowed(db: AsyncSession, world: World) -> None:
    service = RoutineToolService(db)
    trigger = world.trigger
    await db.delete(trigger)
    await db.flush()
    with pytest.raises(AuthorizationError):
        await service.replace_settings(world.ctx, trigger, RoutineToolSettings())


async def test_off_hides_the_tool_and_refuses_a_call_to_it(db: AsyncSession, world: World) -> None:
    await save(db, world, EXECUTE.model_dump())
    authority = await capture(db, world)
    (hide,) = authority.tools_off(world.spec)
    visible = await hide.prepare_tools(None, [sandbox("execute"), sandbox("read_file")])  # type: ignore[arg-type]  # the hook never reads its run context
    assert [tool.name for tool in visible] == ["read_file"]
    with pytest.raises(AuthorizationError, match="turned off"):
        await authority.action_policy(world.agent.id, world.spec, sandbox("execute"))
    assert not (
        await authority.action_policy(world.agent.id, world.spec, sandbox("read_file"))
    ).required


async def test_ask_requires_approval_where_the_agent_runs_freely(
    db: AsyncSession, world: World
) -> None:
    authority = await capture(db, world)
    assert not (
        await authority.action_policy(world.agent.id, world.spec, sandbox("execute"))
    ).required
    assert authority.tools_off(world.spec) == ()
    await save(db, world, {**EXECUTE.model_dump(), "setting": "ask"})
    # Saved mid-run: the next call asks, before any new run starts.
    decision = await authority.action_policy(world.agent.id, world.spec, sandbox("execute"))
    assert decision.required and decision.consented_by is None


async def test_a_delegate_and_an_unknown_tool_are_not_narrowed(
    db: AsyncSession, world: World
) -> None:
    await save(db, world, EXECUTE.model_dump())
    authority = await capture(db, world)
    assert await authority._narrowed(db, uuid4(), world.spec, sandbox("execute")) is None
    assert await authority._narrowed(db, world.agent.id, world.spec, sandbox("invented")) is None
    unrecorded = replace(authority, tool_settings=None)
    assert await unrecorded._narrowed(db, world.agent.id, world.spec, sandbox("execute")) is None


async def test_unreadable_settings_refuse_rather_than_release(
    db: AsyncSession, world: World
) -> None:
    world.trigger.tool_settings = [{"capability_id": "sandbox", "setting": "maybe"}]
    await db.flush()
    with pytest.raises(AuthorizationError):
        await capture(db, world)


async def test_a_replacement_overwrites_unreadable_settings(db: AsyncSession, world: World) -> None:
    world.trigger.tool_settings = [{"capability_id": "sandbox", "setting": "maybe"}]
    await db.flush()
    await save(db, world, EXECUTE.model_dump())
    assert read_tool_settings(world.trigger.tool_settings) == {
        RoutineActionKey(capability_id="sandbox", tool_id="execute"): "off"
    }


async def test_a_tool_the_provider_runs_is_never_offered_nor_enforced_silently(
    db: AsyncSession, world: World
) -> None:
    fetch = RoutineCapabilityToolSetting(
        capability_id="web_fetch", tool_id="web_fetch", setting="off"
    )
    native = AgentSpec(
        name="Worker",
        capabilities=[CapabilityBindingSpec(id="web_fetch", config={"method": "native"})],
    )
    local = AgentSpec(
        name="Worker",
        capabilities=[CapabilityBindingSpec(id="web_fetch", config={"method": "local"})],
    )
    assert capability_tool_options(native, local=False) == []
    assert [option.tool_id for option in capability_tool_options(local, local=False)] == [
        "web_fetch"
    ]
    world.trigger.tool_settings = [fetch.model_dump(mode="json")]
    await db.flush()
    authority = await capture(db, world)
    assert len(authority.tools_off(local)) == 1
    # Narrowed while the agent ran it, then handed to the provider: refused, not released.
    with pytest.raises(AuthorizationError) as refused:
        authority.tools_off(native)
    assert refused.value.details == {"tools": ["web_fetch"]}


def test_two_narrowings_never_add_up_to_a_release() -> None:
    assert stricter("ask", "off") == "off"
    assert stricter(None, "ask") == "ask"
    assert stricter(None, None) is None


def test_stored_settings_read_back_as_written() -> None:
    connection = uuid4()
    stored = tool_settings_of(
        {
            RoutineActionKey(capability_id="sandbox", tool_id="execute"): "off",
            RoutineMcpToolKey(connection_id=connection, tool_id="send_mail"): "ask",
            RoutinePlatformActionKey(kind="platform", tool_id="invite_member"): "off",
        }
    )
    assert {type(setting) for setting in stored} == {
        RoutineCapabilityToolSetting,
        RoutineMcpToolSetting,
        RoutinePlatformToolSetting,
    }
    assert read_tool_settings([setting.model_dump(mode="json") for setting in stored]) == {
        RoutineActionKey(capability_id="sandbox", tool_id="execute"): "off",
        RoutineMcpToolKey(connection_id=connection, tool_id="send_mail"): "ask",
        RoutinePlatformActionKey(kind="platform", tool_id="invite_member"): "off",
    }


async def _org_mail(db: AsyncSession, world: World) -> McpConnection:
    connection = McpConnection(
        scope="org",
        purpose="mcp",
        organization_id=world.org.id,
        name="Mail",
        label="Work",
        url="https://mail.example/mcp",
        is_enabled=True,
        allowed_tools=["send_mail", "read_mail"],
        last_tools=[
            {"name": "send_mail", "description": "Send", "read_only": False},
            {"name": "read_mail", "description": "Read", "read_only": True},
            {"name": "drop_mail", "description": "Excluded", "read_only": False},
        ],
    )
    db.add(connection)
    await db.flush()
    world.spec = world.spec.model_copy(
        update={
            "mcp_servers": [
                OrgMcpServerRef(
                    account="organization",
                    connection_id=connection.id,
                    approval="writes",
                )
            ]
        }
    )
    world.version.spec = world.spec.model_dump(mode="json")
    await db.flush()
    reviewed_sources(
        world.trigger,
        spec=world.spec,
        version_id=world.version.id,
        sources={
            connection.id: McpSourceIdentity(
                endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
                authorization_generation=connection.authorization_generation,
                tool_prefix=tool_prefix(connection.name),
            )
        },
        tools=("send_mail", "read_mail"),
    )
    await db.flush()
    return connection


async def test_mcp_tools_are_listed_by_connection_and_narrowed_at_run_time(
    db: AsyncSession, world: World
) -> None:
    connection = await _org_mail(db, world)
    options = await RoutineToolService(db).tools(world.ctx, world.trigger)
    mcp = {item.tool_id: item for item in options.items if isinstance(item, RoutineMcpToolOption)}
    assert set(mcp) == {"send_mail", "read_mail"}
    assert mcp["send_mail"].agent == "ask" and mcp["send_mail"].effect
    assert mcp["read_mail"].agent == "free" and not mcp["read_mail"].effect
    assert mcp["read_mail"].account_name == "Work (Mail)"
    await save(
        db, world, {"connection_id": str(connection.id), "tool_id": "read_mail", "setting": "off"}
    )
    authority = await capture(db, world)
    origin = {
        MCP_ORIGIN: McpToolOrigin(
            connection_id=connection.id,
            identity=McpSourceIdentity(
                endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
                authorization_generation=connection.authorization_generation,
                tool_prefix=tool_prefix(connection.name),
            ),
            tool_id="read_mail",
        )
    }
    assert authority.tool_key(
        world.spec, ToolDefinition(name="mail_read_mail", metadata=origin)
    ) == RoutineMcpToolKey(connection_id=connection.id, tool_id="read_mail")


async def test_accounts_without_a_readable_tool_list_are_named_not_listed(
    db: AsyncSession, world: World
) -> None:
    connection = await _org_mail(db, world)
    connection.last_tools = None
    disabled = McpConnection(
        scope="user",
        purpose="mcp",
        user_id=world.ctx.subject_id,
        name="Personal",
        catalog_key="github",
        url="https://github.example/mcp",
        is_enabled=False,
        last_tools=[],
    )
    own = McpConnection(
        scope="user",
        purpose="mcp",
        user_id=world.ctx.subject_id,
        name="GitHub",
        label="GitHub",
        catalog_key="github",
        url="https://github.example/mcp",
        is_enabled=True,
        last_tools=[{"name": "list_issues", "description": "List", "read_only": True}],
    )
    db.add_all([disabled, own])
    world.spec = world.spec.model_copy(
        update={
            "mcp_servers": [
                *world.spec.mcp_servers,
                PersonalMcpServerRef(account="personal", catalog_key="github"),
            ]
        }
    )
    world.version.spec = world.spec.model_dump(mode="json")
    world.trigger.runs_as_creator = True
    await db.flush()
    options = await RoutineToolService(db).tools(world.ctx, world.trigger)
    assert options.unavailable_sources == ["Work (Mail)"]
    (listed,) = [item for item in options.items if isinstance(item, RoutineMcpToolOption)]
    assert listed.account_name == "GitHub" and listed.account_scope == "personal"
    # A switched-off account offers nothing, and needs no check either.
    connection.is_enabled = False
    await db.flush()
    assert (await RoutineToolService(db).tools(world.ctx, world.trigger)).unavailable_sources == []
    connection.is_enabled = True
    # Without acting as its creator, a routine reaches no personal account at all.
    world.trigger.runs_as_creator = False
    await db.flush()
    assert (await RoutineToolService(db).tools(world.ctx, world.trigger)).unavailable_sources == [
        "Work (Mail)"
    ]


async def test_platform_tools_leave_out_the_routines_own_report(
    db: AsyncSession, world: World
) -> None:
    world.spec = world.spec.model_copy(
        update={
            "mcp_servers": [
                PlatformMcpServerRef(
                    account="platform",
                    approval="writes",
                    allowed_tools=["list_virtual_tables", "invite_member", "publish_inbox_finding"],
                )
            ]
        }
    )
    world.version.spec = world.spec.model_dump(mode="json")
    world.trigger.runs_as_creator = True
    await db.flush()
    reviewed_sources(world.trigger, spec=world.spec, version_id=world.version.id)
    await db.flush()
    options = await RoutineToolService(db).tools(world.ctx, world.trigger)
    platform = {
        item.tool_id: item for item in options.items if isinstance(item, RoutinePlatformToolOption)
    }
    assert set(platform) == {"list_virtual_tables", "invite_member"}
    assert platform["list_virtual_tables"].agent == "free"
    assert platform["invite_member"].agent == "ask" and platform["invite_member"].effect
    await save(db, world, {"kind": "platform", "tool_id": "list_virtual_tables", "setting": "off"})
    authority = await capture(db, world)
    listing = ToolDefinition(name="agenticos_list_virtual_tables", metadata={PLATFORM_TOOL: True})
    with pytest.raises(AuthorizationError, match="turned off"):
        await authority.action_policy(world.agent.id, world.spec, listing)
    unknown = ToolDefinition(name="agenticos_invented", metadata={PLATFORM_TOOL: True})
    assert authority.tool_key(world.spec, unknown) is None


async def test_readiness_counts_only_what_the_owner_set_to_ask(
    db: AsyncSession, world: World
) -> None:
    await save(
        db,
        world,
        {**EXECUTE.model_dump(), "setting": "ask"},
        {"capability_id": "sandbox", "tool_id": "ls", "setting": "off"},
    )
    found = await blockers(db, world.trigger, creator=world.ctx, paused_for_budget=False)
    (asking,) = [blocker for blocker in found if blocker.code == "actions_need_approval"]
    assert asking.count == 1
    await save(db, world)
    found = await blockers(db, world.trigger, creator=world.ctx, paused_for_budget=False)
    assert all(blocker.code != "actions_need_approval" for blocker in found)


async def test_readiness_counts_nothing_when_the_version_cannot_be_read(
    db: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.routine_readiness import _narrowed_to_ask

    async def unavailable(*_args: object) -> object:
        raise NotFoundError(message="Agent not found")

    monkeypatch.setattr(RoutineToolService, "tools", unavailable)
    assert await _narrowed_to_ask(db, world.ctx, world.trigger) == 0


async def test_hiding_keeps_every_tool_it_was_not_asked_to_hide() -> None:
    keep = RoutineToolsOff(hidden=lambda tool: tool.name == "execute")
    tools = await keep.prepare_tools(None, [sandbox("ls"), sandbox("execute")])  # type: ignore[arg-type]  # the hook never reads its run context
    assert [tool.name for tool in tools] == ["ls"]


async def test_ask_only_narrowing_keeps_the_tool_visible(db: AsyncSession, world: World) -> None:
    await save(db, world, {"capability_id": "sandbox", "tool_id": "read_file", "setting": "ask"})
    authority = await capture(db, world)
    assert authority.tools_off(world.spec) == ()


async def test_an_unavailable_tool_restriction_is_listed_and_preserved_explicitly(
    db: AsyncSession, world: World
) -> None:
    connection = await _org_mail(db, world)
    rule = {"connection_id": str(connection.id), "tool_id": "read_mail", "setting": "off"}
    await save(db, world, rule)
    connection.last_tools = None
    await db.flush()
    review = await RoutineToolService(db).tools(world.ctx, world.trigger)
    assert review.unavailable_settings == [RoutineMcpToolSetting.model_validate(rule)]
    await save(db, world, rule, EXECUTE.model_dump())
    assert len(read_tool_settings(world.trigger.tool_settings)) == 2
    # Unknown historical keys may be preserved exactly, not changed into a
    # different request for a tool the version has not offered.
    with pytest.raises(BadRequestError):
        await save(db, world, {**rule, "setting": "ask"})
    await save(db, world, EXECUTE.model_dump())
    assert not (await RoutineToolService(db).tools(world.ctx, world.trigger)).unavailable_settings


async def test_unreadable_storage_cannot_introduce_an_unknown_tool(
    db: AsyncSession, world: World
) -> None:
    world.trigger.tool_settings = [{"invalid": True}]
    await db.flush()
    with pytest.raises(BadRequestError):
        await save(db, world, {"capability_id": "sandbox", "tool_id": "invented", "setting": "off"})
