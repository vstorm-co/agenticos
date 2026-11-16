"""Standing consent cannot escape its owner, routine intent or published version."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import load_builtins
from app.agents.mcp import McpSourceIdentity
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.routine_actions import RoutineActionKey, RoutineActions
from app.services.routine_actions import RoutineActionService, action_review
from app.services.routine_authority import RoutineAuthority
from app.services.routine_sources import read_policy
from tests.routine_source_support import reviewed_sources

pytestmark = [pytest.mark.anyio, pytest.mark.security]
WRITE = RoutineActionKey(capability_id="sandbox", tool_id="execute")


@dataclass
class World:
    ctx: AuthContext
    org: Organization
    member: OrganizationMember
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
    org = Organization(
        name="Acme",
        slug=f"acme-{uuid4()}",
        created_by_user_id=user.id,
        chat_may_waive_approvals=True,
    )
    db.add(org)
    await db.flush()
    member = OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")
    agent = Agent(
        organization_id=org.id,
        owner_user_id=user.id,
        name="Worker",
        slug=f"worker-{uuid4()}",
        status="published",
    )
    db.add_all([member, agent])
    await db.flush()
    spec = AgentSpec(name="Worker", capabilities=[{"id": "sandbox"}])
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
    )
    db.add(trigger)
    await db.flush()
    reviewed_sources(trigger, spec=spec, version_id=version.id)
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr("app.services.routine_authority.get_db_context", context)
    return World(ctx, org, member, agent, version, trigger, spec)


def _request(world: World, actions: list[RoutineActionKey]) -> RoutineActions:
    return RoutineActions(
        actions=actions, review_token=action_review(world.trigger, world.version.id)
    )


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


def tool(name: str = "execute", capability: str | None = "sandbox") -> ToolDefinition:
    return ToolDefinition(name=name, capability_id=capability)


async def test_native_writes_ask_but_reads_do_not(db: AsyncSession, world: World) -> None:
    authority = await capture(db, world)
    assert (await authority.action_policy(world.agent.id, world.spec, tool())).required
    assert not (
        await authority.action_policy(world.agent.id, world.spec, tool("read_file"))
    ).required
    unknown = await authority.action_policy(world.agent.id, world.spec, tool("new_tool", "sandbox"))
    assert unknown.required and unknown.consented_by is None
    external = tool("mail_send", None)
    assert (await authority.action_policy(world.agent.id, world.spec, external)).required
    external.metadata = {"annotations": {"readOnlyHint": True}}
    assert not (await authority.action_policy(world.agent.id, world.spec, external)).required


async def test_only_a_current_snapshotted_consent_waives_its_action(
    db: AsyncSession, world: World
) -> None:
    service = RoutineActionService(db)
    before = await capture(db, world)
    options = await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    assert next(item for item in options.items if item.tool_id == WRITE.tool_id).consented
    assert (await before.action_policy(world.agent.id, world.spec, tool())).consented_by is None
    authority = await capture(db, world)
    assert (
        await authority.action_policy(world.agent.id, world.spec, tool())
    ).consented_by == world.ctx.user_id
    assert (
        await authority.action_policy(world.agent.id, world.spec, tool("write_file"))
    ).consented_by is None
    await service.replace(world.ctx, world.trigger, RoutineActions())
    assert (await authority.action_policy(world.agent.id, world.spec, tool())).consented_by is None
    await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    assert (await authority.action_policy(world.agent.id, world.spec, tool())).consented_by is None


@pytest.mark.parametrize(
    "change", ["prompt", "version", "owner", "policy", "permission", "intent", "delegate"]
)
async def test_standing_consent_never_survives_changed_authority(
    db: AsyncSession, world: World, change: str
) -> None:
    await RoutineActionService(db).replace(world.ctx, world.trigger, _request(world, [WRITE]))
    authority = await capture(db, world)
    if change == "prompt":
        world.trigger.prompt = "Different job"
    elif change == "version":
        authority = replace(authority, root_version_id=uuid4())
    elif change == "owner":
        consent = dict(world.trigger.action_consents[0])
        consent["consented_by"] = str(uuid4())
        world.trigger.action_consents = [consent]
    elif change == "policy":
        world.org.chat_may_waive_approvals = False
    elif change == "permission":
        world.member.role = "member"
        authority = replace(authority, role="member")
    elif change == "intent":
        world.trigger.answer_to = "primary"
    elif change == "delegate":
        delegate = Agent(
            organization_id=world.org.id,
            name="Delegate",
            slug=f"delegate-{uuid4()}",
            owner_user_id=world.ctx.user_id,
        )
        db.add(delegate)
        await db.flush()
        decision = await authority.action_policy(delegate.id, world.spec, tool())
        assert decision.required and decision.consented_by is None
        return
    await db.flush()
    if change == "intent":
        with pytest.raises(AuthorizationError):
            await authority.action_policy(world.agent.id, world.spec, tool())
    else:
        decision = await authority.action_policy(world.agent.id, world.spec, tool())
        assert decision.required and decision.consented_by is None


@pytest.mark.parametrize("actor", ["api-key", "routine", "fallback", "other-owner"])
async def test_a_model_or_another_actor_cannot_consent(
    db: AsyncSession, world: World, actor: str
) -> None:
    changes: dict[str, object] = {}
    if actor == "api-key":
        changes["api_key_id"] = uuid4()
    elif actor == "routine":
        changes["routine_id"] = world.trigger.id
    elif actor == "fallback":
        changes["subject_is_publisher_fallback"] = True
    else:
        changes["user_id"] = uuid4()
    with pytest.raises(AuthorizationError):
        await RoutineActionService(db).replace(
            replace(world.ctx, **changes), world.trigger, _request(world, [WRITE])
        )
    assert world.trigger.action_consents == []


async def test_duplicate_unknown_and_explicitly_required_actions_cannot_be_waived(
    db: AsyncSession, world: World
) -> None:
    service = RoutineActionService(db)
    for actions in (
        [WRITE, WRITE],
        [RoutineActionKey(capability_id="clock", tool_id="execute")],
    ):
        with pytest.raises(BadRequestError):
            await service.replace(world.ctx, world.trigger, _request(world, actions))
    world.version.spec = AgentSpec(
        name="Worker", capabilities=[{"id": "sandbox", "approval": "required"}]
    ).model_dump(mode="json")
    await db.flush()
    options = await service.options(world.ctx, world.trigger)
    assert all(not item.waivable for item in options.items)
    with pytest.raises(BadRequestError):
        await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))


async def test_a_resumed_run_cannot_adopt_newly_granted_consent(
    db: AsyncSession, world: World
) -> None:
    from app.db.models.agent_run import AgentRun

    service = RoutineActionService(db)
    await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    admitted = list(world.trigger.action_consents)
    run = AgentRun(
        organization_id=world.org.id,
        user_id=world.ctx.user_id,
        agent_version_id=world.version.id,
        routine_origin_id=world.trigger.id,
        routine_kind="trigger",
        initiated_by_publisher_fallback=True,
        surface="schedule",
        routine_policy={
            "approved_sources": world.trigger.approved_sources,
            "action_consents": admitted,
        },
    )
    await service.replace(world.ctx, world.trigger, RoutineActions())
    await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    restored = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    assert restored is not None
    assert (await restored.action_policy(world.agent.id, world.spec, tool())).consented_by is None
    run.routine_policy = None
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)


async def test_local_file_mutations_and_remote_delegation_are_actions(
    db: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.trigger.local_target = {
        "folder": "/reports",
        "routine_grant": str(uuid4()),
        "operations": {"read": True, "write": True, "execute": False},
        "mode": "workspace_write",
        "device_id": str(uuid4()),
    }
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.routine_authority.session_repo.active_device",
        AsyncMock(return_value=object()),
    )
    await db.flush()
    authority = await capture(db, world)
    assert (await authority.action_policy(world.agent.id, world.spec, tool("write_file"))).required
    options = await RoutineActionService(db).options(world.ctx, world.trigger)
    assert "write_file" in {option.tool_id for option in options.items}
    delegation = AgentSpec(name="Worker", capabilities=[{"id": "subagents"}])
    assert (
        await authority.action_policy(world.agent.id, delegation, tool("task", "subagents"))
    ).required


@pytest.mark.parametrize("restriction", ["policy", "permission"])
async def test_disallowed_standing_consent_can_still_be_revoked(
    db: AsyncSession, world: World, restriction: str
) -> None:
    service = RoutineActionService(db)
    await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    ctx = world.ctx
    if restriction == "policy":
        world.org.chat_may_waive_approvals = False
        await db.flush()
    else:
        ctx = replace(ctx, role=OrgRoleName.MEMBER)
    with pytest.raises(AuthorizationError):
        await service.replace(ctx, world.trigger, _request(world, [WRITE]))
    await service.replace(ctx, world.trigger, RoutineActions())
    assert world.trigger.action_consents == []


async def test_consent_uses_the_pinned_version_and_ignores_disabled_bindings(
    db: AsyncSession, world: World
) -> None:
    world.trigger.pinned_version_id = world.version.id
    await db.flush()
    result = await RoutineActionService(db).replace(
        world.ctx, world.trigger, _request(world, [WRITE])
    )
    assert any(option.consented for option in result.items)
    disabled = world.spec.model_copy(
        update={
            "capabilities": [
                binding.model_copy(update={"enabled": False}) for binding in world.spec.capabilities
            ]
        }
    )
    reviewed_sources(world.trigger, spec=world.spec, version_id=world.version.id)
    await db.flush()
    authority = await capture(db, world)
    denied = await authority.action_policy(world.agent.id, disabled, tool())
    assert denied.required and denied.consented_by is None
    from app.services.routine_actions import action_options

    assert action_options(disabled) == []


async def test_missing_routines_and_corrupt_consent_are_refused(
    db: AsyncSession, world: World
) -> None:
    world.trigger.action_consents = [{"capability_id": "sandbox"}]
    await db.flush()
    with pytest.raises(AuthorizationError):
        await capture(db, world)
    await db.delete(world.trigger)
    await db.flush()
    with pytest.raises(AuthorizationError):
        await RoutineActionService(db).replace(world.ctx, world.trigger, RoutineActions())


async def test_unreviewed_work_or_version_cannot_gain_consent(
    db: AsyncSession, world: World
) -> None:
    from app.core.exceptions import ConflictError

    request = _request(world, [WRITE])
    world.trigger.prompt = "New work after the dialog opened"
    await db.flush()
    with pytest.raises(ConflictError):
        await RoutineActionService(db).replace(world.ctx, world.trigger, request)
    assert world.trigger.action_consents == []
    with pytest.raises(ConflictError):
        await RoutineActionService(db).replace(
            world.ctx, world.trigger, RoutineActions(actions=[WRITE])
        )


@pytest.mark.parametrize(
    "change",
    [
        "unchanged",
        "reauthorize",
        "reauthorize-resume",
        "prefix",
        "endpoint",
        "disabled",
        "tools",
        "another-account",
        "removed",
        "foreign",
        "publisher",
        "legacy",
    ],
)
async def test_resumed_mcp_calls_remain_bound_to_the_admitted_account(
    db: AsyncSession, world: World, change: str
) -> None:
    import hashlib

    from app.agents.mcp import MCP_ORIGIN, McpSourceIdentity, McpToolOrigin
    from app.db.models.agent_run import AgentRun
    from app.db.models.mcp_connection import McpConnection
    from app.services.routine_authority import MCP_SOURCES

    connection = McpConnection(
        scope="org",
        purpose="mcp",
        organization_id=world.org.id,
        name="Work account",
        url="https://service.example/mcp",
        is_enabled=True,
    )
    db.add(connection)
    await db.flush()
    identity = McpSourceIdentity(
        endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
        authorization_generation=connection.authorization_generation,
        tool_prefix="work_account",
    )
    reviewed_sources(
        world.trigger,
        spec=world.spec,
        version_id=world.version.id,
        sources={connection.id: identity},
        tools=("write",),
    )
    snapshot = MCP_SOURCES.dump_python({connection.id: identity}, mode="json")
    run = AgentRun(
        organization_id=world.org.id,
        user_id=world.ctx.user_id,
        agent_version_id=world.version.id,
        routine_origin_id=world.trigger.id,
        routine_kind="trigger",
        initiated_by_publisher_fallback=True,
        surface="schedule",
        routine_policy={
            "approved_sources": world.trigger.approved_sources,
            "action_consents": [],
            "mcp_sources": snapshot,
        },
    )
    if change in ("reauthorize", "reauthorize-resume"):
        connection.authorization_generation = uuid4()
    elif change == "endpoint":
        connection.url = "https://different.example/mcp"
    elif change == "disabled":
        connection.is_enabled = False
    elif change == "tools":
        connection.allowed_tools = ["read"]
    elif change == "removed":
        await db.delete(connection)
    elif change == "foreign":
        other = Organization(
            name="Other", slug=f"other-{uuid4()}", created_by_user_id=world.ctx.subject_id
        )
        db.add(other)
        await db.flush()
        connection.organization_id = other.id
    elif change == "publisher":
        connection.scope, connection.organization_id, connection.user_id = (
            "user",
            None,
            world.ctx.subject_id,
        )
    elif change == "legacy":
        run.routine_policy = None
    await db.flush()
    if change in {"legacy", "reauthorize", "reauthorize-resume", "endpoint", "disabled", "removed"}:
        with pytest.raises(AuthorizationError):
            await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
        return
    restored = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    assert restored is not None
    if change == "reauthorize-resume":
        identity = replace(identity, authorization_generation=connection.authorization_generation)
    elif change == "prefix":
        identity = replace(identity, tool_prefix="different_account")
    origin = McpToolOrigin(
        connection_id=uuid4() if change == "another-account" else connection.id,
        identity=identity,
        tool_id="write",
    )
    call = ToolDefinition(name="fitted_or_renamed_write", metadata={MCP_ORIGIN: origin})
    if change == "unchanged":
        assert restored.mcp_sources == {connection.id: identity}
        assert (await restored.action_policy(world.agent.id, world.spec, call)).required
    else:
        with pytest.raises(AuthorizationError):
            await restored.action_policy(world.agent.id, world.spec, call)


@pytest.fixture
async def mcp_account(db: AsyncSession, world: World) -> McpConnection:
    from app.agents.spec import OrgMcpServerRef

    connection = McpConnection(
        scope="org",
        purpose="mcp",
        organization_id=world.org.id,
        name="Mail",
        label="Work",
        url="https://mail.example/mcp",
        is_enabled=True,
        last_tools=[
            {"name": "send_mail", "description": "Send an email", "read_only": False},
            {"name": "delete_mail", "description": "Delete an email", "read_only": False},
            {"name": "read_mail", "description": "Read an email", "read_only": True},
        ],
    )
    db.add(connection)
    await db.flush()
    world.spec = world.spec.model_copy(
        update={
            "mcp_servers": [OrgMcpServerRef(account="organization", connection_id=connection.id)]
        }
    )
    world.version.spec = world.spec.model_dump(mode="json")
    await db.flush()
    reviewed_sources(
        world.trigger,
        spec=world.spec,
        version_id=world.version.id,
        sources={connection.id: mcp_source(connection)},
        tools=("send_mail", "delete_mail", "read_mail"),
    )
    await db.flush()
    return connection


def mcp_source(connection: McpConnection) -> McpSourceIdentity:
    import hashlib

    from app.agents.mcp import tool_prefix

    return McpSourceIdentity(
        endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
        authorization_generation=connection.authorization_generation,
        tool_prefix=tool_prefix(connection.name),
    )


def mcp_call(connection: McpConnection, name: str) -> ToolDefinition:
    from app.agents.mcp import MCP_ORIGIN, McpToolOrigin, fitted_tool_name

    identity = mcp_source(connection)
    return ToolDefinition(
        name=fitted_tool_name(f"{identity.tool_prefix}_{name}"),
        metadata={MCP_ORIGIN: McpToolOrigin(connection.id, identity, name)},
    )


async def test_one_review_can_consent_to_native_and_one_account_action_together(
    db: AsyncSession, world: World, mcp_account: McpConnection
) -> None:
    from app.schemas.routine_actions import RoutineMcpActionOption
    from app.services.routine_actions import action_key

    service = RoutineActionService(db)
    offered = await service.options(world.ctx, world.trigger)
    actions = [item for item in offered.items if isinstance(item, RoutineMcpActionOption)]
    assert {item.tool_id for item in actions} == {"send_mail", "delete_mail"}
    assert all(
        item.account_name == "Work (Mail)" and item.account_scope == "organization"
        for item in actions
    )
    send = next(item for item in actions if item.tool_id == "send_mail")
    saved = await service.replace(
        world.ctx,
        world.trigger,
        RoutineActions(
            actions=[WRITE, action_key(send)],
            review_token=offered.review_token,
        ),
    )
    assert sum(item.consented for item in saved.items) == 2
    admitted = replace(
        await capture(db, world), mcp_sources={mcp_account.id: mcp_source(mcp_account)}
    )
    decision = await admitted.action_policy(
        world.agent.id, world.spec, mcp_call(mcp_account, "send_mail")
    )
    assert decision.required and decision.consented_by == world.ctx.user_id
    assert (
        await admitted.action_policy(
            world.agent.id, world.spec, mcp_call(mcp_account, "delete_mail")
        )
    ).consented_by is None
    assert (
        await admitted.action_policy(world.agent.id, world.spec, tool())
    ).consented_by == world.ctx.user_id
    # Revoking and regranting the same actions cannot release older parked work.
    await service.replace(world.ctx, world.trigger, RoutineActions())
    await service.replace(
        world.ctx,
        world.trigger,
        RoutineActions(
            actions=[action_key(send)],
            review_token=(await service.options(world.ctx, world.trigger)).review_token,
        ),
    )
    assert (
        await admitted.action_policy(world.agent.id, world.spec, mcp_call(mcp_account, "send_mail"))
    ).consented_by is None


async def test_account_reconsent_invalidates_a_stale_review_without_widening_authority(
    db: AsyncSession, world: World, mcp_account: McpConnection
) -> None:
    from app.core.exceptions import ConflictError
    from app.schemas.routine_actions import RoutineMcpActionOption
    from app.services.routine_actions import action_key

    service = RoutineActionService(db)
    offered = await service.options(world.ctx, world.trigger)
    send = next(
        item
        for item in offered.items
        if isinstance(item, RoutineMcpActionOption) and item.tool_id == "send_mail"
    )
    mcp_account.authorization_generation = uuid4()
    await db.flush()
    with pytest.raises(ConflictError):
        await service.replace(
            world.ctx,
            world.trigger,
            RoutineActions(actions=[action_key(send)], review_token=offered.review_token),
        )
    assert world.trigger.action_consents == []


async def test_explicit_mcp_approval_and_intersected_tool_limits_cannot_be_waived(
    db: AsyncSession, world: World, mcp_account: McpConnection
) -> None:
    from app.schemas.routine_actions import RoutineMcpActionOption
    from app.services.routine_actions import action_key

    ref = world.spec.mcp_servers[0].model_copy(
        update={"approval": "writes", "allowed_tools": ["send_mail"]}
    )
    world.spec = world.spec.model_copy(update={"mcp_servers": [ref]})
    world.version.spec = world.spec.model_dump(mode="json")
    mcp_account.allowed_tools = ["send_mail"]
    await db.flush()
    service = RoutineActionService(db)
    offered = await service.options(world.ctx, world.trigger)
    actions = [item for item in offered.items if isinstance(item, RoutineMcpActionOption)]
    assert len(actions) == 1 and actions[0].tool_id == "send_mail" and not actions[0].waivable
    with pytest.raises(BadRequestError):
        await service.replace(
            world.ctx,
            world.trigger,
            RoutineActions(actions=[action_key(actions[0])], review_token=offered.review_token),
        )
    mcp_account.allowed_tools = ["delete_mail"]
    await db.flush()
    assert all(
        not isinstance(item, RoutineMcpActionOption)
        for item in (await service.options(world.ctx, world.trigger)).items
    )


async def test_each_mcp_tool_s_own_approval_decides_whether_consent_can_waive_it(
    db: AsyncSession, world: World, mcp_account: McpConnection
) -> None:
    """A tool the agent lets run takes standing consent under `writes`, and one it
    asks before takes none under `none` (#2884)."""
    from app.schemas.routine_actions import RoutineMcpActionOption

    async def waivable(approval: str, tool_approval: dict[str, str]) -> dict[str, bool]:
        ref = world.spec.mcp_servers[0].model_copy(
            update={"approval": approval, "tool_approval": tool_approval}
        )
        world.version.spec = world.spec.model_copy(update={"mcp_servers": [ref]}).model_dump(
            mode="json"
        )
        await db.flush()
        offered = await RoutineActionService(db).options(world.ctx, world.trigger)
        return {
            item.tool_id: item.waivable
            for item in offered.items
            if isinstance(item, RoutineMcpActionOption)
        }

    assert await waivable("writes", {"send_mail": "never"}) == {
        "send_mail": True,
        "delete_mail": False,
    }
    assert await waivable("none", {"delete_mail": "required"}) == {
        "send_mail": True,
        "delete_mail": False,
    }


@pytest.mark.parametrize("metadata", [None, [{"invalid": "provider metadata"}]])
async def test_unavailable_account_inventory_is_visible_and_cannot_block_revocation(
    db: AsyncSession,
    world: World,
    mcp_account: McpConnection,
    metadata: list[dict[str, str]] | None,
) -> None:
    mcp_account.last_tools = metadata
    await db.flush()
    service = RoutineActionService(db)
    offered = await service.options(world.ctx, world.trigger)
    assert offered.unavailable_sources == ["Work (Mail)"]
    assert all(isinstance(item, RoutineActionKey) for item in offered.items)
    assert (
        await service.replace(world.ctx, world.trigger, RoutineActions())
    ).unavailable_sources == ["Work (Mail)"]
    assert world.trigger.action_consents == []


async def test_personal_account_exceptions_require_personal_authority_and_the_same_owner(
    db: AsyncSession, world: World, mcp_account: McpConnection
) -> None:
    from app.agents.spec import PersonalMcpServerRef
    from app.schemas.routine_actions import RoutineMcpActionKey, RoutineMcpActionOption
    from app.services.routine_actions import action_key

    other = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(other)
    await db.flush()
    own = McpConnection(
        scope="user",
        purpose="mcp",
        user_id=world.ctx.subject_id,
        name="Personal",
        catalog_key="github",
        url="https://mail.example/mcp",
        last_tools=mcp_account.last_tools,
        is_enabled=True,
    )
    foreign = McpConnection(
        scope="user",
        purpose="mcp",
        user_id=other.id,
        name="Foreign",
        catalog_key="github",
        url="https://mail.example/mcp",
        last_tools=mcp_account.last_tools,
        is_enabled=True,
    )
    db.add_all([own, foreign])
    world.spec = world.spec.model_copy(
        update={"mcp_servers": [PersonalMcpServerRef(account="personal", catalog_key="github")]}
    )
    world.version.spec = world.spec.model_dump(mode="json")
    await db.flush()
    service = RoutineActionService(db)
    assert all(
        not isinstance(item, RoutineMcpActionOption)
        for item in (await service.options(world.ctx, world.trigger)).items
    )
    world.trigger.runs_as_creator = True
    await db.flush()
    offered = await service.options(world.ctx, world.trigger)
    actions = [item for item in offered.items if isinstance(item, RoutineMcpActionOption)]
    assert actions and all(
        item.connection_id == own.id and item.account_scope == "personal" for item in actions
    )
    forged = RoutineMcpActionKey(
        connection_id=foreign.id,
        endpoint_hash=mcp_source(foreign).endpoint_hash,
        authorization_generation=foreign.authorization_generation,
        tool_id="send_mail",
    )
    with pytest.raises(BadRequestError):
        await service.replace(
            world.ctx,
            world.trigger,
            RoutineActions(actions=[forged], review_token=offered.review_token),
        )
    send = next(item for item in actions if item.tool_id == "send_mail")
    await service.replace(
        world.ctx,
        world.trigger,
        RoutineActions(actions=[action_key(send)], review_token=offered.review_token),
    )
    policy = reviewed_sources(
        world.trigger,
        spec=world.spec,
        version_id=world.version.id,
        sources={own.id: mcp_source(own)},
        tools=("send_mail", "delete_mail", "read_mail"),
    )
    await db.flush()
    ctx = replace(
        world.ctx,
        routine_id=world.trigger.id,
        fired_as_creator="schedule",
        routine_source_policy_id=policy.id,
    )
    admitted = await RoutineAuthority.capture(
        db, ctx, agent_id=world.agent.id, version_id=world.version.id, run=None
    )
    assert admitted is not None
    admitted = replace(admitted, mcp_sources={own.id: mcp_source(own)})
    assert (
        await admitted.action_policy(world.agent.id, world.spec, mcp_call(own, "send_mail"))
    ).consented_by == world.ctx.user_id


async def test_an_account_exception_cannot_authorize_another_account_or_routine(
    db: AsyncSession, world: World, mcp_account: McpConnection
) -> None:
    from app.agents.spec import OrgMcpServerRef
    from app.schemas.routine_actions import RoutineMcpActionOption
    from app.services.routine_actions import action_key

    other_account = McpConnection(
        scope="org",
        purpose="mcp",
        organization_id=world.org.id,
        name="Other mail",
        url=mcp_account.url,
        last_tools=mcp_account.last_tools,
        is_enabled=True,
    )
    db.add(other_account)
    await db.flush()
    world.spec = world.spec.model_copy(
        update={
            "mcp_servers": [
                *world.spec.mcp_servers,
                OrgMcpServerRef(account="organization", connection_id=other_account.id),
            ]
        }
    )
    world.version.spec = world.spec.model_dump(mode="json")
    await db.flush()
    service = RoutineActionService(db)
    offered = await service.options(world.ctx, world.trigger)
    send = next(
        item
        for item in offered.items
        if isinstance(item, RoutineMcpActionOption)
        and item.connection_id == mcp_account.id
        and item.tool_id == "send_mail"
    )
    await service.replace(
        world.ctx,
        world.trigger,
        RoutineActions(actions=[action_key(send)], review_token=offered.review_token),
    )
    sources = {connection.id: mcp_source(connection) for connection in (mcp_account, other_account)}
    reviewed_sources(
        world.trigger,
        spec=world.spec,
        version_id=world.version.id,
        sources=sources,
        tools=("send_mail", "delete_mail", "read_mail"),
    )
    await db.flush()
    original = replace(await capture(db, world), mcp_sources=sources)
    assert (
        await original.action_policy(
            world.agent.id, world.spec, mcp_call(other_account, "send_mail")
        )
    ).consented_by is None
    other_routine = AgentTrigger(
        organization_id=world.org.id,
        agent_id=world.agent.id,
        created_by_user_id=world.ctx.subject_id,
        prompt=world.trigger.prompt,
        interval_seconds=300,
        next_fire_at=datetime.now(UTC),
    )
    db.add(other_routine)
    await db.flush()
    policy = reviewed_sources(
        other_routine,
        spec=world.spec,
        version_id=world.version.id,
        sources=sources,
        tools=("send_mail", "delete_mail", "read_mail"),
    )
    await db.flush()
    other_ctx = replace(
        world.ctx,
        routine_id=other_routine.id,
        subject_is_publisher_fallback=True,
        routine_source_policy_id=policy.id,
    )
    other = await RoutineAuthority.capture(
        db, other_ctx, agent_id=world.agent.id, version_id=world.version.id, run=None
    )
    assert other is not None
    other = replace(other, mcp_sources=sources)
    assert (
        await other.action_policy(world.agent.id, world.spec, mcp_call(mcp_account, "send_mail"))
    ).consented_by is None


async def test_a_pause_observed_during_the_final_consent_read_refuses_the_call(
    db: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repositories import agent_trigger_repo

    await RoutineActionService(db).replace(world.ctx, world.trigger, _request(world, [WRITE]))
    admitted = await capture(db, world)
    original = agent_trigger_repo.get_by_id

    async def pause_on_read(*args: object, **kwargs: object) -> AgentTrigger | None:
        row = await original(db, world.trigger.id, fresh=True)
        assert row is not None
        row.is_active = False
        await db.flush()
        return row

    monkeypatch.setattr(agent_trigger_repo, "get_by_id", pause_on_read)
    with pytest.raises(AuthorizationError):
        await admitted.action_policy(world.agent.id, world.spec, tool())


@pytest.mark.parametrize("binding", ["skill", "resource", "context", "project"])
async def test_instruction_edits_invalidate_review_tokens_and_standing_consent(
    db: AsyncSession, world: World, binding: str
) -> None:
    from app.db.models.context import ContextFile
    from app.db.models.project import Project
    from app.db.models.skill import Skill, SkillResource
    from app.services.routine_actions import instruction_fingerprint

    if binding in {"skill", "resource"}:
        skill = Skill(
            organization_id=world.org.id,
            owner_user_id=world.ctx.user_id,
            name="instructions",
            description="Instructions",
            content="Original instructions",
        )
        db.add(skill)
        await db.flush()
        world.spec.skill_ids = [skill.id]
        if binding == "resource":
            target = SkillResource(skill_id=skill.id, name="policy.md", content="Original policy")
            db.add(target)
        else:
            target = skill
    elif binding == "context":
        target = ContextFile(
            organization_id=world.org.id,
            owner_user_id=world.ctx.user_id,
            name="policy",
            content="Original policy",
        )
        db.add(target)
        await db.flush()
        world.spec.context_ids = [target.id]
    else:
        target = Project(
            organization_id=world.org.id,
            owner_user_id=world.ctx.user_id,
            name="Policy",
            instructions="Original policy",
            backend="state",
        )
        db.add(target)
        await db.flush()
        world.trigger.project_id = target.id
    await db.flush()
    world.version.spec = world.spec.model_dump(mode="json")
    reviewed_sources(world.trigger, spec=world.spec, version_id=world.version.id)
    await db.flush()
    service = RoutineActionService(db)
    offered = await service.options(world.ctx, world.trigger)
    request = RoutineActions(actions=[WRITE], review_token=offered.review_token)
    await service.replace(world.ctx, world.trigger, request)
    authority = await capture(db, world)
    assert (await authority.action_policy(world.agent.id, world.spec, tool())).consented_by
    before = await instruction_fingerprint(
        db, organization_id=world.org.id, spec=world.spec, project_id=world.trigger.project_id
    )
    if isinstance(target, Project):
        original = target.instructions
        target.instructions = "Changed instructions"
    else:
        original = target.content
        target.content = "Changed instructions"
    target.updated_at = datetime.now(UTC)
    await db.flush()
    with pytest.raises(ConflictError):
        await service.replace(world.ctx, world.trigger, request)
    # A change in a project may also invalidate source authorization itself.
    try:
        decision = await authority.action_policy(world.agent.id, world.spec, tool())
    except AuthorizationError:
        assert binding == "project"
    else:
        assert decision.required and decision.consented_by is None
    if isinstance(target, Project):
        target.instructions = original
    else:
        target.content = original
    target.updated_at = datetime.now(UTC)
    await db.flush()
    after = await instruction_fingerprint(
        db, organization_id=world.org.id, spec=world.spec, project_id=world.trigger.project_id
    )
    assert after != before
    assert not next(
        item
        for item in (await service.options(world.ctx, world.trigger)).items
        if item.tool_id == WRITE.tool_id
    ).consented
    # Legacy consents without an instruction revision cannot waive bound content.
    world.trigger.action_consents = [
        {key: value for key, value in consent.items() if key != "instructions_hash"}
        for consent in world.trigger.action_consents
    ]
    await db.flush()
    legacy = await capture(db, world)
    assert (await legacy.action_policy(world.agent.id, world.spec, tool())).consented_by is None


async def test_recreated_skill_resource_cannot_reactivate_its_previous_consent(
    db: AsyncSession, world: World
) -> None:
    from app.db.models.skill import Skill, SkillResource

    skill = Skill(
        organization_id=world.org.id,
        owner_user_id=world.ctx.user_id,
        name="recreated-resource",
        description="Policy",
        content="Read policy.md",
    )
    db.add(skill)
    await db.flush()
    resource = SkillResource(skill_id=skill.id, name="policy.md", content="Original policy")
    db.add(resource)
    world.spec.skill_ids = [skill.id]
    world.version.spec = world.spec.model_dump(mode="json")
    reviewed_sources(world.trigger, spec=world.spec, version_id=world.version.id)
    await db.flush()
    service = RoutineActionService(db)
    offered = await service.options(world.ctx, world.trigger)
    await service.replace(
        world.ctx, world.trigger, RoutineActions(actions=[WRITE], review_token=offered.review_token)
    )
    authority = await capture(db, world)
    assert (await authority.action_policy(world.agent.id, world.spec, tool())).consented_by
    await db.delete(resource)
    await db.flush()
    db.add(SkillResource(skill_id=skill.id, name="policy.md", content="Original policy"))
    await db.flush()
    assert (await authority.action_policy(world.agent.id, world.spec, tool())).consented_by is None


@pytest.mark.parametrize("binding", ["skill", "context"])
async def test_delegate_instruction_edits_invalidate_the_parent_fingerprint(
    db: AsyncSession, world: World, binding: str
) -> None:
    from app.agents.spec import AgentSpec, SubagentRef
    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.context import ContextFile
    from app.db.models.skill import Skill
    from app.services.routine_actions import instruction_fingerprint

    if binding == "context":
        target = ContextFile(
            organization_id=world.org.id,
            owner_user_id=world.ctx.user_id,
            name="Delegate instructions",
            content="Original",
        )
    else:
        target = Skill(
            organization_id=world.org.id,
            owner_user_id=world.ctx.user_id,
            name="delegate-instructions",
            description="Delegate instructions",
            content="Original",
        )
    db.add(target)
    await db.flush()
    child = Agent(
        organization_id=world.org.id,
        owner_user_id=world.ctx.user_id,
        name="Delegate",
        slug=f"delegate-{uuid4().hex}",
    )
    db.add(child)
    await db.flush()
    spec = AgentSpec(
        name="Delegate",
        context_ids=[target.id] if binding == "context" else [],
        skill_ids=[target.id] if binding == "skill" else [],
    )
    version = AgentVersion(
        organization_id=world.org.id,
        agent_id=child.id,
        version=1,
        spec=spec.model_dump(mode="json"),
    )
    db.add(version)
    await db.flush()
    world.spec.subagents = [SubagentRef(agent_id=child.id, agent_version_id=version.id)]
    before = await instruction_fingerprint(
        db, organization_id=world.org.id, spec=world.spec, project_id=None
    )
    target.content = "Changed delegate instructions"
    target.updated_at = datetime.now(UTC)
    await db.flush()
    after = await instruction_fingerprint(
        db, organization_id=world.org.id, spec=world.spec, project_id=None
    )
    assert before is not None and after != before


@pytest.mark.parametrize(
    "change", ["missing_organization", "missing_member", "malformed_consents", "missing_version"]
)
async def test_standing_consent_refuses_removed_or_corrupt_authority(
    db, world, monkeypatch, change
):
    from unittest.mock import AsyncMock

    from app.services import routine_authority

    await RoutineActionService(db).replace(world.ctx, world.trigger, _request(world, [WRITE]))
    authority = await capture(db, world)
    if change == "missing_organization":
        monkeypatch.setattr(
            routine_authority.organization_repo, "get_by_id", AsyncMock(return_value=None)
        )
    elif change == "missing_member":
        monkeypatch.setattr(
            routine_authority.member_repo, "get_active", AsyncMock(return_value=None)
        )
    elif change == "malformed_consents":
        world.trigger.action_consents = [{"invalid": True}]
        await db.flush()
    else:
        monkeypatch.setattr(
            routine_authority.agent_repo, "get_version", AsyncMock(return_value=None)
        )
    if change == "missing_version":
        assert await authority._consent_in(db, world.agent.id, WRITE) is None
    else:
        with pytest.raises(AuthorizationError):
            await authority._consent_in(db, world.agent.id, WRITE)


async def test_publisher_routine_does_not_offer_a_persons_unreviewed_mcp_account(db, world):
    from app.agents.spec import PersonalMcpServerRef

    world.trigger.runs_as_creator = False
    world.spec.mcp_servers = [PersonalMcpServerRef(catalog_key="github", account="personal")]
    options, unavailable = await RoutineActionService(db)._mcp_options(
        world.ctx, world.trigger, world.spec
    )
    assert options == [] and unavailable == []


@pytest.mark.parametrize("purpose,enabled", [("mcp", False), ("account", True)])
async def test_mcp_action_review_omits_disabled_and_account_only_connections(
    db: AsyncSession, world: World, purpose: str, enabled: bool
) -> None:
    from app.agents.spec import OrgMcpServerRef

    connection = McpConnection(
        scope="org",
        purpose=purpose,
        organization_id=world.org.id,
        name="Unavailable work account",
        url="https://service.example/mcp",
        is_enabled=enabled,
        last_tools=[{"name": "write", "description": "Write", "inputSchema": {"type": "object"}}],
    )
    db.add(connection)
    await db.flush()
    world.spec.mcp_servers = [OrgMcpServerRef(connection_id=connection.id)]
    options, unavailable = await RoutineActionService(db)._mcp_options(
        world.ctx, world.trigger, world.spec
    )
    assert options == [] and unavailable == []


@pytest.mark.parametrize("change", ["title", "cadence", "intent", "version", "instructions"])
async def test_action_review_distinguishes_retained_consent_from_explicit_reselection(
    db: AsyncSession, world: World, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = RoutineActionService(db)
    await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    if change == "title":
        world.trigger.name = "A clearer name"
    elif change == "cadence":
        world.trigger.interval_seconds = 600
    elif change == "intent":
        world.trigger.prompt = "Different work"
    elif change == "version":
        version = AgentVersion(
            agent_id=world.agent.id,
            organization_id=world.org.id,
            version=2,
            spec=world.spec.model_dump(mode="json"),
        )
        db.add(version)
        await db.flush()
        world.agent.current_version_id = version.id
    else:
        from unittest.mock import AsyncMock

        monkeypatch.setattr(
            "app.services.routine_actions.instruction_fingerprint", AsyncMock(return_value="f" * 64)
        )
    await db.flush()
    offered = await service.options(world.ctx, world.trigger)
    action = next(item for item in offered.items if item.tool_id == WRITE.tool_id)
    assert action.previously_consented is True
    if change in {"title", "cadence"}:
        assert action.consented is True
        assert offered.review_changes == []
    else:
        assert action.consented is False
        assert change in offered.review_changes


async def test_a_changed_action_is_explained_without_regranting_it(
    db: AsyncSession, world: World
) -> None:
    service = RoutineActionService(db)
    await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    stored = dict(world.trigger.action_consents[0])
    stored["tool_id"] = "removed_action"
    world.trigger.action_consents = [stored]
    await db.flush()
    offered = await service.options(world.ctx, world.trigger)
    assert offered.review_changes == ["actions"]
    assert not any(action.previously_consented or action.consented for action in offered.items)
