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
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.routine_actions import RoutineActionKey, RoutineActions
from app.services.routine_actions import RoutineActionService, action_review
from app.services.routine_authority import RoutineAuthority

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
        replace(world.ctx, routine_id=world.trigger.id, subject_is_publisher_fallback=True),
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
        routine_policy={"action_consents": admitted},
    )
    await service.replace(world.ctx, world.trigger, RoutineActions())
    await service.replace(world.ctx, world.trigger, _request(world, [WRITE]))
    restored = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    assert restored is not None
    assert (await restored.action_policy(world.agent.id, world.spec, tool())).consented_by is None
    run.routine_policy = None
    legacy = await RoutineAuthority.capture(db, world.ctx, agent_id=world.agent.id, run=run)
    assert legacy is not None and legacy.action_consents == ()


async def test_local_file_mutations_and_remote_delegation_are_actions(
    db: AsyncSession, world: World
) -> None:
    world.trigger.local_target = {
        "folder": "/reports",
        "mode": "workspace_write",
        "device_id": str(uuid4()),
    }
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
