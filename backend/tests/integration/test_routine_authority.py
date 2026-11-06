"""Revocation is read from Postgres before another routine or delegate tool runs."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.routine_authority import RoutineAuthority
from tests.routine_source_support import reviewed_sources

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class World:
    user: User
    owner: User
    organization: Organization
    member: OrganizationMember
    agent: Agent
    delegate: Agent
    trigger: AgentTrigger
    grant: ResourceGrant
    delegate_grant: ResourceGrant
    ctx: AuthContext


async def _world(db: AsyncSession) -> World:
    owner = User(email=f"{uuid4()}@example.com", hashed_password="x")
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add_all([owner, user])
    await db.flush()
    organization = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=owner.id)
    db.add(organization)
    await db.flush()
    member = OrganizationMember(organization_id=organization.id, user_id=user.id, role="viewer")
    agent = Agent(
        organization_id=organization.id,
        name="Monitor",
        slug=f"monitor-{uuid4()}",
        owner_user_id=owner.id,
    )
    delegate = Agent(
        organization_id=organization.id,
        name="Helper",
        slug=f"helper-{uuid4()}",
        owner_user_id=owner.id,
    )
    db.add_all([member, agent, delegate])
    await db.flush()
    grant = ResourceGrant(
        organization_id=organization.id,
        resource_type="agent",
        resource_id=agent.id,
        subject_user_id=user.id,
        level="use",
    )
    delegate_grant = ResourceGrant(
        organization_id=organization.id,
        resource_type="agent",
        resource_id=delegate.id,
        subject_user_id=user.id,
        level="use",
    )
    trigger = AgentTrigger(
        organization_id=organization.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        prompt="Check",
        interval_seconds=300,
        next_fire_at=datetime.now(UTC),
        runs_as_creator=True,
    )
    db.add_all([grant, delegate_grant, trigger])
    await db.flush()
    policy = reviewed_sources(trigger, spec=AgentSpec(name="Monitor"), version_id=uuid4())
    await db.flush()
    ctx = AuthContext(
        routine_source_policy_id=policy.id,
        user_id=user.id,
        organization_id=organization.id,
        role=OrgRoleName.VIEWER,
        routine_id=trigger.id,
        fired_as_creator="schedule",
    )
    return World(
        user, owner, organization, member, agent, delegate, trigger, grant, delegate_grant, ctx
    )


@pytest.mark.parametrize(
    "change",
    [
        "paused",
        "deleted",
        "expired",
        "consent",
        "role",
        "deactivated",
        "left",
        "root-grant",
        "delegate-deleted",
        "delegate-archived",
        "archived",
        "owner",
        "agent",
    ],
)
async def test_current_authority_can_revoke_a_previously_admitted_tool(
    db: AsyncSession,
    change: str,
) -> None:
    world = await _world(db)
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    await authority.check_in(db, world.delegate.id)
    if change == "paused":
        world.trigger.is_active = False
    elif change == "deleted":
        await db.delete(world.trigger)
    elif change == "expired":
        world.trigger.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "consent":
        world.trigger.runs_as_creator = False
    elif change == "role":
        world.member.role = "owner"
    elif change == "deactivated":
        world.user.is_active = False
    elif change == "left":
        await db.delete(world.member)
    elif change == "root-grant":
        await db.delete(world.grant)
    elif change == "delegate-deleted":
        await db.delete(world.delegate)
    elif change == "delegate-archived":
        world.delegate.status = "archived"
    elif change == "archived":
        world.agent.status = "archived"
    elif change == "owner":
        world.trigger.created_by_user_id = world.owner.id
    elif change == "agent":
        world.trigger.agent_id = world.delegate.id
    await db.flush()
    with pytest.raises(AuthorizationError, match="authorization changed"):
        await authority.check_in(db, world.delegate.id)


async def test_another_tenant_or_root_agent_cannot_borrow_a_routine(db: AsyncSession) -> None:
    world = await _world(db)
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(
            db, replace(world.ctx, organization_id=uuid4()), agent_id=world.agent.id, run=None
        )
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(db, world.ctx, agent_id=world.delegate.id, run=None)
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(
            db, replace(world.ctx, role="owner"), agent_id=world.agent.id, run=None
        )


async def test_resumption_keeps_the_original_actor_and_origin_after_deletion(
    db: AsyncSession,
) -> None:
    world = await _world(db)
    run = await agent_run_repo.create_run(
        db,
        organization_id=world.organization.id,
        agent_id=world.agent.id,
        agent_version_id=None,
        user_id=world.user.id,
        conversation_id=None,
        surface="schedule",
        model_label=None,
        started_at=datetime.now(UTC),
        trigger_id=world.trigger.id,
        routine_policy={"approved_sources": world.trigger.approved_sources},
    )
    approver = replace(world.ctx, user_id=world.owner.id, role="owner", routine_id=None)
    authority = await RoutineAuthority.capture(db, approver, agent_id=world.agent.id, run=run)
    assert (
        authority is not None and authority.user_id == world.user.id and authority.role == "viewer"
    )
    origin = world.trigger.id
    await db.delete(world.trigger)
    await db.flush()
    await db.refresh(run)
    assert run.trigger_id is None and run.routine_origin_id == origin
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(db, approver, agent_id=world.agent.id, run=run)


async def test_unattributed_routine_runs_cannot_borrow_the_resumer(db: AsyncSession) -> None:
    world = await _world(db)
    run = AgentRun(routine_origin_id=world.trigger.id, user_id=None)
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    assert (
        await RoutineAuthority.capture(
            db, replace(world.ctx, routine_id=None), agent_id=world.agent.id, run=None
        )
        is None
    )


async def test_nonpersonal_routines_and_runs_with_no_routine_keep_their_contract(
    db: AsyncSession,
) -> None:
    world = await _world(db)
    world.trigger.runs_as_creator = False
    world.trigger.ends_at = datetime.now(UTC) + timedelta(days=1)
    policy = reviewed_sources(world.trigger, spec=AgentSpec(name="Monitor"), version_id=uuid4())
    await db.flush()
    authority = await RoutineAuthority.capture(
        db,
        replace(world.ctx, fired_as_creator=None, routine_source_policy_id=policy.id),
        agent_id=world.agent.id,
        run=None,
    )
    assert authority is not None and not authority.acts_as_creator
    run = AgentRun(
        routine_origin_id=world.trigger.id,
        user_id=world.user.id,
        initiated_by_publisher_fallback=True,
        routine_kind="trigger",
        routine_policy={"approved_sources": world.trigger.approved_sources},
    )
    resumed = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    assert resumed is not None and not resumed.acts_as_creator
    run.routine_origin_id = None
    assert await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run) is None


async def test_each_tool_checks_current_committed_state_in_a_fresh_session(
    db: AsyncSession,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import routine_authority

    world = await _world(db)
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    opened: list[AsyncSession] = []

    @asynccontextmanager
    async def fresh() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            opened.append(session)
            yield session

    monkeypatch.setattr(routine_authority, "get_db_context", fresh)
    await authority.check(world.agent.id)
    await db.delete(world.grant)
    await db.commit()
    with pytest.raises(AuthorizationError):
        await authority.check(world.agent.id)
    assert len(opened) == 2 and opened[0] is not opened[1]


async def test_a_legacy_parked_routine_with_no_remaining_origin_is_not_released(
    db: AsyncSession,
) -> None:
    world = await _world(db)
    run = AgentRun(surface="schedule", routine_origin_id=None, user_id=world.user.id)
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)


async def test_a_published_parent_lends_its_pinned_delegate_without_a_direct_grant(
    db: AsyncSession,
) -> None:
    world = await _world(db)
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    await db.delete(world.delegate_grant)
    await db.flush()
    await authority.check_in(db, world.delegate.id)


@pytest.mark.parametrize(
    "change",
    [
        "paused",
        "deleted",
        "expired",
        "role",
        "root-grant",
        "corrupt-sources",
        "account-disabled",
        "account-owner",
        "account-endpoint",
        "account-tools",
        "intent",
        "sources",
        "organization-disabled",
        "agent",
    ],
)
async def test_watch_authority_revokes_a_running_read_when_its_approval_changes(
    db: AsyncSession,
    change: str,
) -> None:
    from app.agents.spec import AgentSpec, PersonalMcpServerRef
    from app.db.models.mcp_connection import McpConnection
    from app.db.models.watch import Watch
    from app.services.watch_sources import approve_sources

    world = await _world(db)
    world.organization.proactive_watches_enabled = True
    connection = McpConnection(
        organization_id=None,
        user_id=world.user.id,
        scope="user",
        purpose="mcp",
        name="GitHub",
        catalog_key="github",
        url="https://github.example/mcp",
        is_enabled=True,
    )
    db.add(connection)
    await db.flush()
    spec = AgentSpec(
        name="Monitor", mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="github")]
    )
    sources = approve_sources(spec, connection)
    watch = Watch(
        organization_id=world.organization.id,
        user_id=world.user.id,
        connection_id=connection.id,
        agent_id=world.agent.id,
        title="Reviews",
        instructions="Reviews waiting on me",
        interval_minutes=60,
        next_run_at=datetime.now(UTC),
        approved_sources=sources.model_dump(mode="json"),
    )
    db.add(watch)
    await db.flush()
    ctx = replace(world.ctx, routine_id=watch.id, routine_kind="watch")
    authority = await RoutineAuthority.capture(db, ctx, agent_id=world.agent.id, run=None)
    assert authority is not None and authority.sources is not None
    await authority.check_in(db, world.agent.id)
    # A parked run retains the original approval, independently of the resumer.
    run = await agent_run_repo.create_run(
        db,
        organization_id=world.organization.id,
        agent_id=world.agent.id,
        agent_version_id=None,
        user_id=world.user.id,
        conversation_id=None,
        surface="proactive",
        model_label=None,
        started_at=datetime.now(UTC),
        routine_origin_id=watch.id,
        routine_kind="watch",
        routine_policy=authority.sources.model_dump(mode="json"),
    )
    if change == "corrupt-sources":
        watch.approved_sources = {"invalid": True}
    elif change == "paused":
        watch.is_active = False
    elif change == "deleted":
        await db.delete(watch)
    elif change == "expired":
        watch.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "role":
        world.member.role = "owner"
    elif change == "root-grant":
        await db.delete(world.grant)
    elif change == "account-disabled":
        connection.is_enabled = False
    elif change == "account-owner":
        connection.user_id = world.owner.id
    elif change == "account-endpoint":
        connection.url = "https://a-different-source.example/mcp"
    elif change == "account-tools":
        connection.allowed_tools = []
    elif change == "intent":
        watch.instructions = "A changed purpose requiring a new admission"
    elif change == "sources":
        watch.approved_sources = sources.model_copy(
            update={"collection_ids": (uuid4(),)}
        ).model_dump(mode="json")
    elif change == "organization-disabled":
        world.organization.proactive_watches_enabled = False
    elif change == "agent":
        watch.agent_id = world.delegate.id
    await db.flush()
    with pytest.raises(AuthorizationError):
        await authority.check_in(db, world.agent.id)
    if change not in {"role", "root-grant"}:
        with pytest.raises(AuthorizationError):
            await RoutineAuthority.capture(
                db,
                replace(ctx, user_id=world.owner.id, role="owner"),
                agent_id=world.agent.id,
                run=run,
            )


async def test_parked_watch_policy_from_before_report_modes_keeps_its_original_intent_guard(
    db: AsyncSession,
):
    import hashlib
    import json

    from app.agents.spec import AgentSpec, PersonalMcpServerRef
    from app.db.models.mcp_connection import McpConnection
    from app.db.models.watch import Watch
    from app.services.watch_sources import approve_sources

    world = await _world(db)
    world.organization.proactive_watches_enabled = True
    connection = McpConnection(
        user_id=world.user.id,
        scope="user",
        purpose="mcp",
        name="GitHub",
        catalog_key="github",
        url="https://github.example/mcp",
        is_enabled=True,
    )
    db.add(connection)
    await db.flush()
    sources = approve_sources(
        AgentSpec(
            name="Monitor",
            mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="github")],
        ),
        connection,
    )
    watch = Watch(
        organization_id=world.organization.id,
        user_id=world.user.id,
        connection_id=connection.id,
        agent_id=world.agent.id,
        approved_sources=sources.model_dump(mode="json"),
        instructions="Reviews",
        title="Review",
        interval_minutes=60,
        next_run_at=datetime.now(UTC),
    )
    db.add(watch)
    await db.flush()
    legacy = sources.model_dump(mode="json")
    legacy.pop("intent_version")
    legacy["intent_hash"] = hashlib.sha256(
        json.dumps(
            [watch.instructions, watch.exclusions, watch.urgent, str(watch.source_conversation_id)],
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    run = await agent_run_repo.create_run(
        db,
        organization_id=world.organization.id,
        agent_id=world.agent.id,
        agent_version_id=None,
        user_id=world.user.id,
        conversation_id=None,
        surface="proactive",
        model_label=None,
        started_at=datetime.now(UTC),
        routine_origin_id=watch.id,
        routine_kind="watch",
        routine_policy=legacy,
    )
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    assert (
        authority is not None
        and authority.sources is not None
        and authority.sources.intent_version == 1
    )
    watch.instructions = "A different responsibility"
    await db.flush()
    with pytest.raises(AuthorizationError):
        await authority.check_in(db, world.agent.id)


@pytest.mark.parametrize("change", ["folder", "operations", "replacement", "cleared", "session"])
async def test_live_routine_native_authority_is_revoked_before_another_tool(
    db: AsyncSession, change: str
) -> None:
    from app.db.models.session import Session
    from app.schemas.local_target import LocalTarget

    world = await _world(db)
    device = Session(
        user_id=world.user.id,
        refresh_token_hash=str(uuid4()),
        app_platform="macos",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(device)
    await db.flush()
    local = LocalTarget(
        folder="/work",
        mode="read_only",
        device_id=device.id,
        routine_grant=uuid4(),
        operations={"read": True, "write": False, "execute": False},
    )
    world.trigger.local_target = local.model_dump(mode="json")
    await db.flush()
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    authority.require_local_target(local)
    await authority.check_in(db, world.delegate.id)
    if change == "folder":
        world.trigger.local_target = world.trigger.local_target | {"folder": "/elsewhere"}
    elif change == "operations":
        world.trigger.local_target = world.trigger.local_target | {
            "mode": "workspace_write",
            "operations": {"read": True, "write": True, "execute": False},
        }
    elif change == "replacement":
        world.trigger.local_target = world.trigger.local_target | {"routine_grant": str(uuid4())}
    elif change == "cleared":
        world.trigger.local_target = None
    else:
        device.is_active = False
    await db.flush()
    with pytest.raises(AuthorizationError):
        await authority.check_in(db, world.delegate.id)
    with pytest.raises(AuthorizationError):
        authority.require_local_target(LocalTarget(folder="/elsewhere"))


@pytest.mark.parametrize("public_origin", [False, True])
async def test_resumed_native_workspace_restores_the_original_routine_owner(
    db: AsyncSession, public_origin: bool
) -> None:
    world = await _world(db)
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    approver = replace(
        world.ctx,
        user_id=world.owner.id,
        role="owner",
        routine_id=None,
        fired_as_creator=None,
        source_conversation_id=uuid4(),
    )
    restored = authority.local_context(approver, public_origin=public_origin)
    assert restored.user_id == world.user.id
    assert restored.role == "viewer"
    assert restored.routine_id == world.trigger.id
    assert restored.source_conversation_id is None
    assert restored.fired_as_creator == ("event" if public_origin else "schedule")
    assert approver.user_id == world.owner.id
    with pytest.raises(AuthorizationError):
        authority.local_context(
            replace(approver, organization_id=uuid4()), public_origin=public_origin
        )
    with pytest.raises(AuthorizationError):
        replace(authority, acts_as_creator=False).local_context(
            approver, public_origin=public_origin
        )


async def test_changing_result_policy_requires_a_new_run(db: AsyncSession):
    world = await _world(db)
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    world.trigger.result_mode = "inbox"
    await db.flush()
    with pytest.raises(AuthorizationError):
        await authority.check_in(db, world.agent.id)


async def test_leaving_and_rejoining_cannot_restore_routine_waivers(db: AsyncSession) -> None:
    from app.services.member import end_membership

    world = await _world(db)
    world.trigger.action_consents = [{"tool_name": "send_mail"}]
    world.trigger.approved_sources = {"old_membership": True}
    world.trigger.is_active = True
    await db.flush()
    await end_membership(db, world.member)
    db.add(
        OrganizationMember(
            organization_id=world.organization.id, user_id=world.user.id, role="viewer"
        )
    )
    await db.flush()
    await db.refresh(world.trigger)
    assert not world.trigger.is_active
    assert world.trigger.action_consents == []
    assert world.trigger.approved_sources is None


@pytest.mark.parametrize(
    "change",
    [
        "kind",
        "missing_trigger",
        "local_type",
        "local_length",
        "local_chars",
        "consents",
        "watch_sources",
    ],
)
async def test_resumed_routine_refuses_corrupt_or_removed_original_authority(
    db, monkeypatch, change
):
    world = await _world(db)
    policy = {"approved_sources": world.trigger.approved_sources}
    run = AgentRun(
        user_id=world.user.id,
        routine_origin_id=world.trigger.id,
        routine_kind="trigger",
        routine_policy=policy,
        agent_id=world.agent.id,
        agent_version_id=None,
        surface="schedule",
    )
    if change == "kind":
        run.routine_kind = "unknown"
    elif change == "missing_trigger":
        run.routine_origin_id = uuid4()
    elif change == "local_type":
        policy["local_target_hash"] = 123
    elif change == "local_length":
        policy["local_target_hash"] = "a"
    elif change == "local_chars":
        policy["local_target_hash"] = "z" * 64
    elif change == "consents":
        policy["action_consents"] = [{"invalid": True}]
    elif change == "watch_sources":
        from app.db.models.watch import Watch

        watch = Watch(
            id=uuid4(),
            organization_id=world.organization.id,
            user_id=world.user.id,
            agent_id=world.agent.id,
            instructions="Check",
            approved_sources={},
        )
        from unittest.mock import AsyncMock

        from app.services import routine_authority

        monkeypatch.setattr(
            routine_authority.watch_repo, "get_by_id", AsyncMock(return_value=watch)
        )
        run.routine_kind, run.routine_origin_id, run.routine_policy = "watch", watch.id, {}
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)


@pytest.mark.parametrize("change", ["no_member", "no_execution_access", "allowed"])
async def test_one_shot_authority_requires_current_task_execution_access(db, monkeypatch, change):
    from unittest.mock import AsyncMock

    from app.services import access, task_access

    world = await _world(db)
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    world.trigger.one_shot = True
    await db.flush()
    monkeypatch.setattr(
        access,
        "member_context",
        AsyncMock(return_value=None if change == "no_member" else world.ctx),
    )
    monkeypatch.setattr(
        task_access, "execution_allows", AsyncMock(return_value=change == "allowed")
    )
    if change == "allowed":
        await authority.check_in(db, world.agent.id)
    else:
        with pytest.raises(AuthorizationError):
            await authority.check_in(db, world.agent.id)


@pytest.mark.parametrize("change", ["stale_policy", "invalid_target"])
async def test_current_trigger_snapshot_rejects_stale_review_or_corrupt_local_target(db, change):
    world = await _world(db)
    if change == "stale_policy":
        with pytest.raises(AuthorizationError):
            await RoutineAuthority.capture(
                db,
                replace(world.ctx, routine_source_policy_id=uuid4()),
                agent_id=world.agent.id,
                run=None,
            )
        return
    authority = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    world.trigger.local_target = {"invalid": True}
    await db.flush()
    with pytest.raises(AuthorizationError):
        await authority._trigger_in(db)
