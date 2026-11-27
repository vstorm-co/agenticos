"""A routine's one access review: its sources and a setting for each of its agent's tools.

See `docs/design/routine-access.md`. The review is saved by its creator in person;
`allow` never releases an approval the agent asks for, and on a tool that changes
something it needs `approvals:decide` and the organization's standing consent.
"""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai.tools import ToolDefinition
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import load_builtins
from app.agents.capabilities._registry import ToolOverride
from app.agents.mcp import MCP_ORIGIN, PLATFORM_TOOL, McpSourceIdentity, McpToolOrigin, tool_prefix
from app.agents.spec import (
    AgentSpec,
    CapabilityBindingSpec,
    OrgMcpServerRef,
    PersonalMcpServerRef,
    PlatformMcpServerRef,
    SubagentRef,
)
from app.core.audit import set_impersonator
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.mcp_connection import McpConnection
from app.db.models.notification import Notification
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.agent_trigger import TriggerCreate
from app.schemas.organization import OrganizationUpdate
from app.schemas.routine_access import (
    RoutineAccessReview,
    RoutineAccessUpdate,
    RoutineCapabilityToolOption,
    RoutineMcpToolOption,
    RoutinePlatformToolOption,
)
from app.schemas.routine_sources import RoutineSourcePolicy
from app.schemas.routine_tool_keys import (
    RoutineCapabilityToolKey,
    RoutineCapabilityToolSetting,
    RoutineMcpToolKey,
)
from app.services.agent_trigger import AgentTriggerService
from app.services.organization import OrganizationService
from app.services.routine_access import (
    RoutineAccessService,
    capability_tool_options,
    in_console,
    settings_of,
)
from app.services.routine_authority import RoutineAuthority
from app.services.routine_readiness import blockers
from app.services.routine_sources import (
    RoutineSourceService,
    RoutineSourcesRequired,
    RoutineTrustRefused,
    read_policy,
)
from tests.routine_source_support import reviewed_sources

pytestmark = [pytest.mark.anyio, pytest.mark.security]


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
    """An owner's schedule over a sandbox agent, reviewed as the console creates it.

    `read_file` and `ls` read, `execute` changes something and runs freely, and
    the agent asks before `write_file`.
    """
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
    spec = AgentSpec(
        name="Worker",
        capabilities=[
            CapabilityBindingSpec(id="sandbox", tool_approval={"write_file": "required"})
        ],
    )
    version = AgentVersion(
        agent_id=agent.id, organization_id=org.id, version=1, spec=spec.model_dump(mode="json")
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    agent.draft_spec = spec.model_dump(mode="json")
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
    trigger.approved_sources = (await RoutineAccessService(db).initial(ctx, trigger)).model_dump(
        mode="json"
    )
    await db.flush()

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr("app.services.routine_authority.get_db_context", context)
    return World(ctx, org, member, agent, version, trigger, spec)


def sandbox(tool_id: str, setting: str) -> dict[str, str]:
    return {"capability_id": "sandbox", "tool_id": tool_id, "setting": setting}


def call(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, capability_id="sandbox")


async def access(db: AsyncSession, world: World, ctx: AuthContext | None = None):
    return await AgentTriggerService(db).access(ctx or world.ctx, world.agent.id, world.trigger.id)


async def save(
    db: AsyncSession,
    world: World,
    *tools: dict[str, str],
    ctx: AuthContext | None = None,
    token: str | None = None,
    **update: object,
) -> RoutineAccessReview:
    actor = ctx or world.ctx
    if token is None:
        token = (await access(db, world, actor)).review_token
    return await AgentTriggerService(db).set_access(
        actor,
        world.agent.id,
        world.trigger.id,
        RoutineAccessUpdate.model_validate({"review_token": token, "tools": [*tools], **update}),
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


async def publish(db: AsyncSession, world: World, spec: AgentSpec) -> None:
    """Replace what the routine's version says, as a republish would."""
    world.spec = spec
    world.version.spec = spec.model_dump(mode="json")
    await db.flush()


async def become(db: AsyncSession, world: World, role: str) -> None:
    world.member.role = role
    world.ctx = replace(world.ctx, role=role)
    await db.flush()


async def allow_trust(db: AsyncSession, world: World, allowed: bool = True) -> None:
    world.org.routines_may_trust_agent = allowed
    await db.flush()


async def audits(db: AsyncSession, action: str) -> list[AppAdminAuditLog]:
    return list(
        (
            await db.execute(select(AppAdminAuditLog).where(AppAdminAuditLog.action == action))
        ).scalars()
    )


def shown(review: RoutineAccessReview) -> dict[str, str | None]:
    return {
        option.tool_id: option.setting
        for option in review.tools
        if isinstance(option, RoutineCapabilityToolOption)
    }


def effective(review: RoutineAccessReview) -> dict[str, str | None]:
    return {
        option.tool_id: option.effective
        for option in review.tools
        if isinstance(option, RoutineCapabilityToolOption)
    }


async def delegating(db: AsyncSession, world: World) -> Agent:
    """Let the routine's agent delegate to a published helper, and review it again."""
    child = Agent(
        organization_id=world.org.id,
        owner_user_id=world.ctx.user_id,
        name="Helper",
        slug=f"helper-{uuid4()}",
        status="published",
    )
    db.add(child)
    await db.flush()
    child_version = AgentVersion(
        agent_id=child.id, organization_id=world.org.id, version=1, spec=world.spec.model_dump()
    )
    db.add(child_version)
    await db.flush()
    child.current_version_id = child_version.id
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={
                "capabilities": [*world.spec.capabilities, CapabilityBindingSpec(id="subagents")],
                "subagents": [SubagentRef(agent_id=child.id, agent_version_id=child_version.id)],
            }
        ),
    )
    world.trigger.approved_sources = (
        await RoutineAccessService(db).initial(world.ctx, world.trigger)
    ).model_dump(mode="json")
    await db.flush()
    return child


# The review, as the console reads it


async def test_the_review_lists_every_tool_with_the_agents_and_the_routines_setting(
    db: AsyncSession, world: World
) -> None:
    review = await access(db, world)
    assert review.current and review.review_reason is None and review.mode == "reviewed"
    assert review.version_id == world.version.id
    options = {o.tool_id: o for o in review.tools if isinstance(o, RoutineCapabilityToolOption)}
    assert options["execute"].effect and options["execute"].agent == "free"
    assert not options["read_file"].effect and options["read_file"].agent == "free"
    assert options["write_file"].agent == "ask"
    assert options["execute"].capability_name == "Sandbox"
    # Created by an owner: every tool they may let run, runs. Only the allow on a
    # change is a setting of the routine's own; the read and the tool the agent
    # asks before take the mode's default.
    assert shown(review)["execute"] == "allow"
    assert shown(review)["read_file"] is None and shown(review)["write_file"] is None
    assert effective(review)["execute"] == "consent"
    assert effective(review)["read_file"] == "run" and effective(review)["write_file"] == "ask"
    assert review.can_allow and review.allow_blocked_reason is None
    assert not review.can_trust and review.trust_blocked_reason == "organization"
    assert not review.has_delegates and review.delegates == "allow"


async def test_a_tool_added_since_the_review_shows_no_setting(
    db: AsyncSession, world: World
) -> None:
    reviewed_sources(
        world.trigger,
        spec=world.spec,
        version_id=world.version.id,
        settings=(
            RoutineCapabilityToolSetting(capability_id="sandbox", tool_id="ls", setting="off"),
        ),
    )
    await db.flush()
    settings = shown(await access(db, world))
    assert settings["ls"] == "off" and settings["execute"] is None


async def test_a_grandfathered_review_shows_what_it_does_follow_the_agent(
    db: AsyncSession, world: World
) -> None:
    reviewed_sources(
        world.trigger, spec=world.spec, version_id=world.version.id, grandfathered=True
    )
    await db.flush()
    settings = shown(await access(db, world))
    assert settings["execute"] == "allow" and settings["write_file"] == "ask"


async def test_a_routine_not_reviewed_yet_shows_what_a_review_would_give(
    db: AsyncSession, world: World
) -> None:
    world.trigger.approved_sources = {"pending_review": True, "unavailable_sources": []}
    await db.flush()
    await become(db, world, OrgRoleName.BUILDER)
    review = await access(db, world)
    assert not review.current and review.review_reason == "setup"
    assert shown(review)["execute"] == "ask" and shown(review)["read_file"] == "allow"
    assert review.delegates == "ask"
    assert not review.can_allow and review.allow_blocked_reason == "permission"


# Who may review


@pytest.mark.parametrize(
    "identity", ["other", "routine", "fallback", "internal_key", "unscoped_key"]
)
async def test_only_the_creator_in_person_may_review_or_save(
    db: AsyncSession, world: World, identity: str
) -> None:
    ctx = {
        "other": replace(world.ctx, user_id=uuid4()),
        "routine": replace(world.ctx, routine_id=world.trigger.id),
        "fallback": replace(world.ctx, subject_is_publisher_fallback=True),
        "internal_key": replace(
            world.ctx, api_key_id=uuid4(), key_internal=True, key_scopes=frozenset(Perm)
        ),
        "unscoped_key": replace(
            world.ctx,
            api_key_id=uuid4(),
            key_scopes=frozenset(Perm) - {Perm.PERSONAL_CONSENT},
        ),
    }[identity]
    service = RoutineAccessService(db)
    with pytest.raises(AuthorizationError):
        await service.review(ctx, world.trigger)
    with pytest.raises(AuthorizationError):
        await service.replace(ctx, world.trigger, RoutineAccessUpdate(review_token="0" * 64))


async def test_an_impersonated_owner_cannot_review(db: AsyncSession, world: World) -> None:
    set_impersonator(uuid4())
    try:
        with pytest.raises(AuthorizationError):
            await access(db, world)
        assert not in_console(world.ctx)
    finally:
        set_impersonator(None)


async def test_a_personal_consent_key_may_narrow_but_not_release_or_trust(
    db: AsyncSession, world: World
) -> None:
    key = replace(world.ctx, api_key_id=uuid4(), key_scopes=frozenset(Perm))
    await allow_trust(db, world)
    review = await access(db, world, key)
    assert not review.can_allow and review.allow_blocked_reason == "console"
    assert not review.can_trust and review.trust_blocked_reason == "console"
    saved = await save(db, world, sandbox("execute", "ask"), sandbox("ls", "off"), ctx=key)
    # Ask on a change is what a reviewed routine does anyway, so it is not stored.
    assert shown(saved)["execute"] is None and effective(saved)["execute"] == "ask"
    assert shown(saved)["ls"] == "off" and effective(saved)["ls"] == "off"
    # A read may run freely by anyone's say.
    await save(db, world, sandbox("read_file", "allow"), ctx=key)
    with pytest.raises(AuthorizationError) as refused:
        await save(db, world, sandbox("execute", "allow"), ctx=key)
    assert refused.value.details == {"reason": "console"}
    with pytest.raises(AuthorizationError) as untrusted:
        await save(db, world, ctx=key, mode="trust_agent")
    assert untrusted.value.details == {"reason": "console"}


# Saving


async def test_saving_stores_only_decisions_and_omitted_tools_take_the_default(
    db: AsyncSession, world: World
) -> None:
    before = read_policy(world.trigger.approved_sources)
    saved = await save(db, world, sandbox("execute", "allow"), sandbox("ls", "off"))
    assert saved.current
    policy = read_policy(world.trigger.approved_sources)
    assert policy.id != before.id and policy.consented_by == world.ctx.user_id
    stored = {setting.tool_id: setting.setting for setting in policy.tools}
    assert stored == {"execute": "allow", "ls": "off"}
    # Left out: a read runs, a tool the agent asks before asks.
    assert effective(saved)["read_file"] == "run" and effective(saved)["write_file"] == "ask"
    assert policy.approved_ceiling is not None and policy.approved_ceiling.tools == ()
    (entry,) = await audits(db, "routine.access_reviewed")
    assert entry.details is not None
    assert entry.details["trigger_id"] == str(world.trigger.id)
    assert (entry.details["allow"], entry.details["off"], entry.details["mode"]) == (
        1,
        1,
        "reviewed",
    )
    assert entry.details["delegates"] == "ask"


@pytest.mark.parametrize("mode", ["reviewed", "trust_agent"])
async def test_an_ask_the_agent_forced_ends_when_the_agent_stops_asking(
    db: AsyncSession, world: World, mode: str
) -> None:
    """Where the agent asks, the review offers only Ask first or Off. Saving that
    Ask first must not keep the routine asking once the agent stops."""
    if mode == "trust_agent":
        await allow_trust(db, world)
    await save(db, world, sandbox("write_file", "ask"), mode=mode)
    assert not read_policy(world.trigger.approved_sources).tools
    await publish(
        db,
        world,
        world.spec.model_copy(update={"capabilities": [CapabilityBindingSpec(id="sandbox")]}),
    )
    review = await access(db, world)
    assert shown(review)["write_file"] is None and effective(review)["write_file"] == "run"
    authority = await capture(db, world)
    assert not (
        await authority.action_policy(world.agent.id, world.spec, call("write_file"))
    ).required


async def test_saving_what_the_review_shows_changes_nothing(db: AsyncSession, world: World) -> None:
    await save(db, world, sandbox("execute", "allow"), sandbox("ls", "off"), sandbox("grep", "ask"))
    before = read_policy(world.trigger.approved_sources).tools
    review = await access(db, world)
    resent = [
        {
            "capability_id": option.capability_id,
            "tool_id": option.tool_id,
            "setting": option.setting,
        }
        for option in review.tools
        if isinstance(option, RoutineCapabilityToolOption) and option.setting is not None
    ]
    await save(db, world, *resent)
    assert read_policy(world.trigger.approved_sources).tools == before


async def test_a_trusting_routine_shows_and_keeps_the_agents_decision_for_a_tool_it_never_set(
    db: AsyncSession, world: World
) -> None:
    await allow_trust(db, world)
    world.org.chat_may_waive_approvals = False
    await db.flush()
    await save(db, world, mode="trust_agent")
    review = await access(db, world)
    # Not shown as asking while it runs, so saving it again cannot start it asking.
    assert shown(review)["execute"] is None and effective(review)["execute"] == "run"
    await save(db, world, mode="trust_agent")
    assert not read_policy(world.trigger.approved_sources).tools
    assert await RoutineAccessService(db).waiting(world.ctx, world.trigger) == 0


async def test_saving_ends_a_grandfathered_review(db: AsyncSession, world: World) -> None:
    reviewed_sources(
        world.trigger, spec=world.spec, version_id=world.version.id, grandfathered=True
    )
    await db.flush()
    await save(db, world, sandbox("execute", "allow"))
    assert not read_policy(world.trigger.approved_sources).grandfathered


async def test_a_stale_token_is_refused_rather_than_reviewed_unseen(
    db: AsyncSession, world: World
) -> None:
    token = (await access(db, world)).review_token
    world.trigger.prompt = "Delete the reports instead"
    await db.flush()
    with pytest.raises(ConflictError):
        await save(db, world, token=token)
    published = world.spec.model_copy(
        update={"capabilities": [*world.spec.capabilities, CapabilityBindingSpec(id="clock")]}
    )
    token = (await access(db, world)).review_token
    await publish(db, world, published)
    with pytest.raises(ConflictError):
        await save(db, world, token=token)


async def test_an_unknown_or_repeated_tool_is_refused(db: AsyncSession, world: World) -> None:
    with pytest.raises(BadRequestError) as unknown:
        await save(db, world, sandbox("invented", "off"))
    assert unknown.value.details == {"tools": ["invented"]}
    with pytest.raises(BadRequestError, match="once"):
        await save(db, world, sandbox("execute", "off"), sandbox("execute", "ask"))


async def test_allow_never_releases_a_tool_the_agent_asks_before(
    db: AsyncSession, world: World
) -> None:
    with pytest.raises(BadRequestError) as refused:
        await save(db, world, sandbox("write_file", "allow"))
    assert refused.value.details == {"tools": ["write_file"]}


@pytest.mark.parametrize("missing", ["permission", "organization"])
async def test_allowing_a_change_needs_approvals_decide_and_the_organization(
    db: AsyncSession, world: World, missing: str
) -> None:
    if missing == "permission":
        await become(db, world, OrgRoleName.BUILDER)
    else:
        world.org.chat_may_waive_approvals = False
        await db.flush()
    with pytest.raises(AuthorizationError) as refused:
        await save(db, world, sandbox("execute", "allow"))
    assert refused.value.details == {"reason": missing}
    # Reads, asking and turning off are anyone's to choose.
    await save(db, world, sandbox("read_file", "allow"), sandbox("execute", "off"))


async def test_letting_delegates_run_needs_the_same_permission(
    db: AsyncSession, world: World
) -> None:
    await delegating(db, world)
    assert (await access(db, world)).has_delegates
    saved = await save(db, world, delegates="allow")
    assert saved.delegates == "allow"
    await become(db, world, OrgRoleName.BUILDER)
    with pytest.raises(AuthorizationError) as refused:
        await save(db, world, delegates="allow")
    assert refused.value.details == {"reason": "permission"}
    assert (await save(db, world, delegates="ask")).delegates == "ask"


async def test_delegates_are_stored_as_ask_where_there_are_none(
    db: AsyncSession, world: World
) -> None:
    saved = await save(db, world, delegates="allow")
    assert saved.delegates == "ask"


# Trusting the agent


async def test_trusting_the_agent_needs_the_organization_the_permission_and_a_schedule(
    db: AsyncSession, world: World
) -> None:
    with pytest.raises(AuthorizationError) as refused:
        await save(db, world, mode="trust_agent")
    assert refused.value.details == {"reason": "organization"}
    await allow_trust(db, world)
    review = await access(db, world)
    assert review.can_trust and review.trust_blocked_reason is None
    saved = await save(db, world, mode="trust_agent")
    assert saved.mode == "trust_agent" and saved.current
    assert read_policy(world.trigger.approved_sources).mode == "trust_agent"
    await become(db, world, OrgRoleName.BUILDER)
    with pytest.raises(AuthorizationError) as builder:
        await save(db, world, mode="trust_agent")
    assert builder.value.details == {"reason": "permission"}


async def test_an_event_routine_cannot_trust_its_agent(db: AsyncSession, world: World) -> None:
    await allow_trust(db, world)
    world.trigger.trigger_type = "event"
    world.trigger.event_source = "webhook"
    world.trigger.event_secret_encrypted = "sealed"
    world.trigger.secret_key_version = 1
    world.trigger.interval_seconds = None
    world.trigger.next_fire_at = None
    await db.flush()
    review = await access(db, world)
    assert review.trust_blocked_reason == "event"
    with pytest.raises(AuthorizationError) as refused:
        await save(db, world, mode="trust_agent")
    assert refused.value.details == {"reason": "event"}


async def test_a_trusting_routine_blocks_once_trust_is_withdrawn(
    db: AsyncSession, world: World
) -> None:
    await allow_trust(db, world)
    await save(db, world, mode="trust_agent")
    policy = read_policy(world.trigger.approved_sources)
    sources = RoutineSourceService(db)
    assert (await sources.require_current(world.ctx, world.trigger, expected_id=policy.id)).id == (
        policy.id
    )
    await allow_trust(db, world, False)
    with pytest.raises(RoutineTrustRefused) as refused:
        await sources.require_current(world.ctx, world.trigger, expected_id=policy.id)
    assert refused.value.details == {"reason": "organization"}
    review = await access(db, world)
    assert not review.current and review.review_reason == "trust_not_allowed"
    found = await blockers(db, world.trigger, creator=world.ctx, paused_for_budget=False)
    assert "trust_not_allowed" in [blocker.code for blocker in found]
    await allow_trust(db, world)
    await become(db, world, OrgRoleName.BUILDER)
    with pytest.raises(RoutineTrustRefused):
        await sources.require_current(world.ctx, world.trigger, expected_id=policy.id)


# Creating a routine


@pytest.mark.parametrize(
    "creator,execute,delegates",
    [("owner", "allow", "allow"), ("builder", "ask", "ask"), ("key", "ask", "ask")],
)
async def test_a_new_routine_lets_run_what_its_creator_may_allow(
    db: AsyncSession, world: World, creator: str, execute: str, delegates: str
) -> None:
    ctx = world.ctx
    if creator == "builder":
        await become(db, world, OrgRoleName.BUILDER)
        ctx = world.ctx
    elif creator == "key":
        ctx = replace(world.ctx, api_key_id=uuid4(), key_scopes=frozenset(Perm))
    created = await AgentTriggerService(db).create(
        ctx, world.agent.id, TriggerCreate(prompt="Check", interval_seconds=300)
    )
    policy = read_policy(created.approved_sources)
    stored = {setting.tool_id: setting.setting for setting in policy.tools}
    # What the creator may not allow is not stored: a change without an allow asks.
    assert stored == ({"execute": "allow"} if execute == "allow" else {})
    assert policy.delegates == delegates and policy.mode == "reviewed"


async def test_review_before_activation_saves_paused_until_the_review_is_saved(
    db: AsyncSession, world: World
) -> None:
    from app.schemas.agent_trigger import TriggerUpdate

    service = AgentTriggerService(db)
    created = await service.create(
        world.ctx,
        world.agent.id,
        TriggerCreate(prompt="Check", interval_seconds=300, review_before_activation=True),
    )
    assert not created.is_active and created.setup_required
    assert created.approved_sources == {"pending_review": True, "unavailable_sources": []}
    with pytest.raises(RoutineSourcesRequired):
        await service.update(world.ctx, world.agent.id, created.id, TriggerUpdate(is_active=True))
    world.trigger = created
    review = await access(db, world)
    assert review.review_reason == "setup"
    await save(db, world, sandbox("execute", "allow"))
    assert not created.setup_required and not created.is_active
    resumed = await service.update(
        world.ctx, world.agent.id, created.id, TriggerUpdate(is_active=True)
    )
    assert resumed.is_active


# Deciding a call


async def test_off_hides_the_tool_and_refuses_a_call_to_it(db: AsyncSession, world: World) -> None:
    await save(db, world, sandbox("execute", "off"), sandbox("read_file", "allow"))
    authority = await capture(db, world)
    (hide,) = authority.tools_off(world.spec)
    visible = await hide.prepare_tools(None, [call("execute"), call("read_file")])  # type: ignore[arg-type]  # the hook never reads its run context
    assert [tool.name for tool in visible] == ["read_file"]
    with pytest.raises(AuthorizationError, match="turned off"):
        await authority.action_policy(world.agent.id, world.spec, call("execute"))
    assert not (
        await authority.action_policy(world.agent.id, world.spec, call("read_file"))
    ).required


async def test_ask_waits_and_allow_runs_as_the_creators_consent(
    db: AsyncSession, world: World
) -> None:
    await save(db, world, sandbox("execute", "ask"), sandbox("read_file", "allow"))
    authority = await capture(db, world)
    assert authority.tools_off(world.spec) == ()
    decision = await authority.action_policy(world.agent.id, world.spec, call("execute"))
    assert decision.required and decision.consented_by is None
    await save(db, world, sandbox("execute", "allow"))
    authority = await capture(db, world)
    decision = await authority.action_policy(world.agent.id, world.spec, call("execute"))
    assert decision.required and decision.consented_by == world.ctx.user_id
    # A read left out of the save runs: the default of a reviewed routine.
    decision = await authority.action_policy(world.agent.id, world.spec, call("read_file"))
    assert not decision.required


async def test_allow_asks_again_once_the_organization_withdraws_standing_consent(
    db: AsyncSession, world: World
) -> None:
    authority = await capture(db, world)
    world.org.chat_may_waive_approvals = False
    await db.flush()
    decision = await authority.action_policy(world.agent.id, world.spec, call("execute"))
    assert decision.required and decision.consented_by is None


async def test_a_changed_role_ends_the_run_rather_than_keep_its_consent(
    db: AsyncSession, world: World
) -> None:
    authority = await capture(db, world)
    world.member.role = OrgRoleName.BUILDER
    await db.flush()
    with pytest.raises(AuthorizationError):
        await authority.action_policy(world.agent.id, world.spec, call("execute"))


async def test_an_effectful_tool_without_a_setting_asks_and_a_read_runs(
    db: AsyncSession, world: World
) -> None:
    reviewed_sources(world.trigger, spec=world.spec, version_id=world.version.id)
    await db.flush()
    authority = await capture(db, world)
    decision = await authority.action_policy(world.agent.id, world.spec, call("execute"))
    assert decision.required and decision.consented_by is None
    assert not (await authority.action_policy(world.agent.id, world.spec, call("ls"))).required
    # A tool the capability does not declare has no authority to guess.
    assert (await authority.action_policy(world.agent.id, world.spec, call("invented"))).required


async def test_a_grandfathered_review_follows_the_agent_without_the_permission(
    db: AsyncSession, world: World
) -> None:
    child = await delegating(db, world)
    reviewed_sources(
        world.trigger,
        spec=world.spec,
        version_id=world.version.id,
        grandfathered=True,
        delegates="allow",
        settings=(
            RoutineCapabilityToolSetting(capability_id="sandbox", tool_id="ls", setting="ask"),
        ),
    )
    world.org.chat_may_waive_approvals = False
    await db.flush()
    authority = await capture(db, world)
    for name in ("execute", "invented"):
        decision = await authority.action_policy(world.agent.id, world.spec, call(name))
        assert not decision.required and decision.consented_by is None
    assert (await authority.action_policy(world.agent.id, world.spec, call("ls"))).required
    delegated = await authority.action_policy(child.id, world.spec, call("execute"))
    assert not delegated.required


async def test_delegates_run_by_the_creators_consent_or_ask(db: AsyncSession, world: World) -> None:
    child = await delegating(db, world)
    authority = await capture(db, world)
    assert read_policy(world.trigger.approved_sources).delegates == "allow"
    decision = await authority.action_policy(child.id, world.spec, call("execute"))
    assert decision.required and decision.consented_by == world.ctx.user_id
    # The root's own settings never reach a delegate's tool of the same name.
    await save(db, world, sandbox("execute", "off"), delegates="ask")
    authority = await capture(db, world)
    decision = await authority.action_policy(child.id, world.spec, call("execute"))
    assert decision.required and decision.consented_by is None
    assert not (await authority.action_policy(child.id, world.spec, call("ls"))).required


async def test_a_trusting_routine_follows_the_agent_except_where_it_says_ask_or_off(
    db: AsyncSession, world: World
) -> None:
    await allow_trust(db, world)
    await save(
        db,
        world,
        sandbox("execute", "allow"),
        sandbox("ls", "ask"),
        sandbox("glob", "off"),
        mode="trust_agent",
    )
    world.org.chat_may_waive_approvals = False
    await db.flush()
    authority = await capture(db, world)
    assert not (await authority.action_policy(world.agent.id, world.spec, call("execute"))).required
    # Left out of the save, so the agent decides.
    assert not (await authority.action_policy(world.agent.id, world.spec, call("grep"))).required
    assert (await authority.action_policy(world.agent.id, world.spec, call("ls"))).required
    with pytest.raises(AuthorizationError, match="turned off"):
        await authority.action_policy(world.agent.id, world.spec, call("glob"))


async def test_a_setting_on_a_tool_the_provider_runs_is_refused_not_dropped(
    db: AsyncSession, world: World
) -> None:
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
    fetch = RoutineCapabilityToolSetting(
        capability_id="web_fetch", tool_id="web_fetch", setting="off"
    )
    reviewed_sources(world.trigger, spec=world.spec, version_id=world.version.id, settings=(fetch,))
    await db.flush()
    authority = await capture(db, world)
    assert authority.tool_settings == {
        RoutineCapabilityToolKey(capability_id="web_fetch", tool_id="web_fetch"): "off"
    }
    assert len(authority.tools_off(local)) == 1
    with pytest.raises(AuthorizationError) as refused:
        authority.tools_off(native)
    assert refused.value.details == {"tools": ["web_fetch"]}
    # Only `ask` and `off` need enforcing; an `allow` is the agent's own decision.
    allowed = replace(
        authority,
        source_policy=read_policy(world.trigger.approved_sources).model_copy(
            update={"tools": (fetch.model_copy(update={"setting": "allow"}),)}
        ),
    )
    assert allowed.tools_off(native) == ()
    assert replace(authority, source_policy=None).tool_settings == {}


# Admission


async def _mail(
    db: AsyncSession, world: World, *, email: str | None = "ops@example.com"
) -> McpConnection:
    """An organization mailbox bound to the agent, reviewed at once."""
    connection = McpConnection(
        scope="org",
        purpose="mcp",
        organization_id=world.org.id,
        name="Mail",
        label="Work",
        url="https://mail.example/mcp",
        is_enabled=True,
        account_email=email,
        allowed_tools=["send_mail", "read_mail"],
        last_tools=[
            {"name": "send_mail", "description": "Send", "read_only": False},
            {"name": "read_mail", "description": "Read", "read_only": True},
            {"name": "drop_mail", "description": "Excluded", "read_only": False},
        ],
    )
    db.add(connection)
    await db.flush()
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={
                "mcp_servers": [
                    OrgMcpServerRef(
                        account="organization", connection_id=connection.id, approval="writes"
                    )
                ]
            }
        ),
    )
    world.trigger.approved_sources = (
        await RoutineAccessService(db).initial(world.ctx, world.trigger)
    ).model_dump(mode="json")
    await db.flush()
    return connection


async def admit(db: AsyncSession, world: World) -> RoutineSourcePolicy:
    return await RoutineSourceService(db).require_current(
        world.ctx, world.trigger, expected_id=read_policy(world.trigger.approved_sources).id
    )


async def test_mcp_tools_are_listed_by_account_with_the_agents_setting(
    db: AsyncSession, world: World
) -> None:
    connection = await _mail(db, world)
    review = await access(db, world)
    mcp = {o.tool_id: o for o in review.tools if isinstance(o, RoutineMcpToolOption)}
    assert set(mcp) == {"send_mail", "read_mail"}
    assert mcp["send_mail"].agent == "ask" and mcp["send_mail"].effect
    assert mcp["read_mail"].agent == "free" and not mcp["read_mail"].effect
    assert mcp["read_mail"].account_name == "Work (Mail)"
    assert mcp["read_mail"].account_scope == "organization"
    # Neither is a decision of the routine's own: the read runs by default, the
    # agent asks before sending.
    assert (mcp["read_mail"].setting, mcp["send_mail"].setting) == (None, None)
    assert (mcp["read_mail"].effective, mcp["send_mail"].effective) == ("run", "ask")
    await save(
        db, world, {"connection_id": str(connection.id), "tool_id": "read_mail", "setting": "off"}
    )
    authority = await capture(db, world)
    origin = McpToolOrigin(
        connection_id=connection.id,
        identity=McpSourceIdentity(
            endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
            authorization_generation=connection.authorization_generation,
            tool_prefix=tool_prefix(connection.name),
        ),
        tool_id="read_mail",
    )
    assert authority.tool_key(
        world.spec, ToolDefinition(name="mail_read_mail", metadata={MCP_ORIGIN: origin})
    ) == RoutineMcpToolKey(connection_id=connection.id, tool_id="read_mail")


async def test_a_save_keeps_the_setting_of_a_tool_it_was_not_shown(
    db: AsyncSession, world: World
) -> None:
    """An account whose tool list is unknown hides its tools from the review;
    saving then must not drop their `off`, or they would run once listed again."""
    connection = await _mail(db, world)
    off = {"connection_id": str(connection.id), "tool_id": "read_mail", "setting": "off"}
    await save(db, world, off)
    listed = connection.last_tools
    connection.last_tools = None
    await db.flush()
    review = await save(db, world)
    assert review.unlisted_accounts == ["Work (Mail)"]
    key = RoutineMcpToolKey(connection_id=connection.id, tool_id="read_mail")
    assert settings_of(read_policy(world.trigger.approved_sources))[key] == "off"
    connection.last_tools = listed
    await db.flush()
    shown = {
        o.tool_id: o.setting
        for o in (await access(db, world)).tools
        if isinstance(o, RoutineMcpToolOption)
    }
    assert shown["read_mail"] == "off"


async def test_accounts_without_a_readable_tool_list_are_named_not_listed(
    db: AsyncSession, world: World
) -> None:
    connection = await _mail(db, world)
    connection.last_tools = None
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
    disabled = McpConnection(
        scope="user",
        purpose="mcp",
        user_id=world.ctx.subject_id,
        name="Personal",
        catalog_key="github",
        url="https://github.example/other",
        is_enabled=False,
        last_tools=[],
    )
    db.add_all([own, disabled])
    world.trigger.runs_as_creator = True
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={
                "mcp_servers": [
                    *world.spec.mcp_servers,
                    PersonalMcpServerRef(account="personal", catalog_key="github"),
                ]
            }
        ),
    )
    review = await access(db, world)
    assert review.unlisted_accounts == ["Work (Mail)"]
    (listed,) = [o for o in review.tools if isinstance(o, RoutineMcpToolOption)]
    assert listed.account_name == "GitHub" and listed.account_scope == "personal"
    # Without acting as its creator, a routine reaches no personal account.
    world.trigger.runs_as_creator = False
    await db.flush()
    review = await access(db, world)
    assert not [o for o in review.tools if isinstance(o, RoutineMcpToolOption)]


@pytest.mark.parametrize("reconnected_as", ["same", "other", "unknown"])
async def test_a_reconnected_account_keeps_its_review_only_as_the_same_account(
    db: AsyncSession, world: World, reconnected_as: str
) -> None:
    connection = await _mail(db, world)
    before = read_policy(world.trigger.approved_sources)
    connection.authorization_generation = uuid4()
    connection.account_email = {
        "same": "ops@example.com",
        "other": "attacker@example.com",
        "unknown": None,
    }[reconnected_as]
    await db.flush()
    if reconnected_as != "same":
        with pytest.raises(RoutineSourcesRequired):
            await admit(db, world)
        return
    admitted = await admit(db, world)
    assert admitted.id == before.id and admitted.tools == before.tools
    assert admitted.mcp_sources[connection.id].authorization_generation == (
        connection.authorization_generation
    )
    # The run reaches the new authorization; the ceiling stays what was reviewed.
    assert admitted.approved_ceiling == before.approved_ceiling
    assert read_policy(world.trigger.approved_sources) == admitted


async def test_an_account_never_named_cannot_reconnect_into_its_review(
    db: AsyncSession, world: World
) -> None:
    connection = await _mail(db, world, email=None)
    connection.authorization_generation = uuid4()
    connection.account_email = "ops@example.com"
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await admit(db, world)


@pytest.mark.parametrize("change", ["new_tool", "changed_binding", "new_capability"])
async def test_a_reviewed_routine_blocks_when_its_agent_reaches_further(
    db: AsyncSession, world: World, change: str
) -> None:
    """A binding is compared as a whole, less its approval settings."""
    connection = await _mail(db, world)
    if change == "new_tool":
        connection.allowed_tools = None
        await db.flush()
    elif change == "changed_binding":
        await publish(
            db,
            world,
            world.spec.model_copy(
                update={
                    "capabilities": [
                        CapabilityBindingSpec(
                            id="sandbox",
                            tool_approval={"write_file": "required"},
                            tool_overrides={"execute": ToolOverride(name="run_shell")},
                        )
                    ]
                }
            ),
        )
    else:
        await publish(
            db,
            world,
            world.spec.model_copy(
                update={
                    "capabilities": [*world.spec.capabilities, CapabilityBindingSpec(id="clock")]
                }
            ),
        )
    with pytest.raises(RoutineSourcesRequired):
        await admit(db, world)
    review = await access(db, world)
    assert not review.current and review.review_reason == "sources"


@pytest.mark.parametrize(
    "tool_approval",
    [{"write_file": "required", "execute": "required"}, {}],
    ids=["stricter", "looser"],
)
async def test_an_agent_changing_only_its_approvals_needs_no_new_review(
    db: AsyncSession, world: World, tool_approval: dict[str, str]
) -> None:
    """The approval gate enforces the agent's settings on every call, and a
    routine can never release one, so changing them grants nothing to review."""
    before = read_policy(world.trigger.approved_sources)
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={
                "capabilities": [CapabilityBindingSpec(id="sandbox", tool_approval=tool_approval)]
            }
        ),
    )
    assert (await admit(db, world)).id == before.id
    assert (await access(db, world)).current


async def test_instructions_alone_change_nothing_reviewed(db: AsyncSession, world: World) -> None:
    before = read_policy(world.trigger.approved_sources)
    await publish(db, world, world.spec.model_copy(update={"instructions": "Be brief."}))
    assert (await admit(db, world)).id == before.id
    assert (await access(db, world)).current


async def test_a_trusting_routine_grows_into_organization_sources_and_says_so_once(
    db: AsyncSession, world: World
) -> None:
    connection = await _mail(db, world)
    await allow_trust(db, world)
    await save(db, world, mode="trust_agent")
    before = read_policy(world.trigger.approved_sources)
    connection.allowed_tools = None
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={"capabilities": [*world.spec.capabilities, CapabilityBindingSpec(id="clock")]}
        ),
    )
    admission = await RoutineSourceService(db).current(
        world.ctx, world.trigger, expected_id=before.id
    )
    assert admission.refreshed and admission.expanded == ["Work"]
    assert read_policy(world.trigger.approved_sources) == before
    admitted = await admit(db, world)
    assert admitted.id == before.id and admitted.mode == "trust_agent"
    assert "drop_mail" in admitted.mcp_sources[connection.id].tool_ids
    assert admitted.approved_ceiling is not None
    assert admitted.approved_ceiling.mcp_sources == admitted.mcp_sources
    assert admitted.tools == before.tools
    (entry,) = await audits(db, "routine.access_expanded")
    assert entry.details == {"trigger_id": str(world.trigger.id), "sources": ["Work"]}
    notified = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_user_id == world.ctx.user_id)
    )
    assert notified == 1
    # The ceiling moved: the next admission has nothing new to report.
    await admit(db, world)
    assert len(await audits(db, "routine.access_expanded")) == 1


async def test_a_trusting_routine_reports_a_changed_agent_as_its_configuration(
    db: AsyncSession, world: World
) -> None:
    await _mail(db, world)
    await allow_trust(db, world)
    await save(db, world, mode="trust_agent")
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={"capabilities": [*world.spec.capabilities, CapabilityBindingSpec(id="clock")]}
        ),
    )
    admission = await RoutineSourceService(db).current(
        world.ctx, world.trigger, expected_id=read_policy(world.trigger.approved_sources).id
    )
    assert admission.expanded == ["agent configuration"]


async def test_a_trusting_routine_leaves_out_a_personal_account_nobody_reviewed(
    db: AsyncSession, world: World
) -> None:
    world.trigger.runs_as_creator = True
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={"mcp_servers": [PersonalMcpServerRef(account="personal", catalog_key="github")]}
        ),
    )
    world.trigger.approved_sources = (
        await RoutineAccessService(db).initial(world.ctx, world.trigger)
    ).model_dump(mode="json")
    await allow_trust(db, world)
    await save(db, world, mode="trust_agent")
    reviewed = McpConnection(
        scope="user",
        purpose="mcp",
        user_id=world.ctx.subject_id,
        name="GitHub",
        catalog_key="github",
        url="https://github.example/mcp",
        is_enabled=True,
        last_tools=[{"name": "list_issues", "description": "List", "read_only": True}],
    )
    db.add(reviewed)
    await db.flush()
    admitted = await admit(db, world)
    assert reviewed.id not in admitted.mcp_sources and admitted.root_mcp_ids == ()
    assert await audits(db, "routine.access_expanded") == []
    # Reviewed now, a new tool on it is still left out until the next review.
    await save(db, world, mode="trust_agent")
    reviewed.last_tools = [
        *reviewed.last_tools,
        {"name": "delete_repo", "description": "Delete", "read_only": False},
    ]
    await db.flush()
    admitted = await admit(db, world)
    assert admitted.mcp_sources[reviewed.id].tool_ids == ("list_issues",)
    assert admitted.mcp_sources[reviewed.id].personal


async def test_a_trusting_routine_blocks_on_a_new_platform_binding(
    db: AsyncSession, world: World
) -> None:
    world.trigger.runs_as_creator = True
    await db.flush()
    world.trigger.approved_sources = (
        await RoutineAccessService(db).initial(world.ctx, world.trigger)
    ).model_dump(mode="json")
    await allow_trust(db, world)
    await save(db, world, mode="trust_agent")
    await publish(
        db,
        world,
        world.spec.model_copy(update={"mcp_servers": [PlatformMcpServerRef(account="platform")]}),
    )
    with pytest.raises(RoutineSourcesRequired):
        await admit(db, world)


# Readiness


async def test_readiness_counts_the_tools_the_routine_makes_ask(
    db: AsyncSession, world: World
) -> None:
    async def asking() -> int | None:
        found = await blockers(db, world.trigger, creator=world.ctx, paused_for_budget=False)
        return next((b.count for b in found if b.code == "actions_need_approval"), None)

    assert await asking() is None
    await save(
        db,
        world,
        sandbox("execute", "ask"),
        sandbox("ls", "off"),
        *(
            sandbox(name, "allow")
            for name in (
                "read_file",
                "glob",
                "grep",
                "edit_file",
                "select_project_workspace",
                "select_execution_target",
            )
        ),
    )
    # `execute` asks because of the routine; `write_file` because of the agent.
    assert await asking() == 1
    await save(
        db,
        world,
        *(
            sandbox(name, "allow")
            for name in (
                "execute",
                "read_file",
                "glob",
                "grep",
                "ls",
                "edit_file",
                "select_project_workspace",
                "select_execution_target",
            )
        ),
    )
    assert await asking() is None
    # Standing consent withdrawn: an allowed change asks again.
    world.org.chat_may_waive_approvals = False
    await db.flush()
    assert await asking() == 1


async def test_readiness_says_a_changed_routine_needs_its_review(
    db: AsyncSession, world: World
) -> None:
    world.trigger.prompt = "Something else"
    await db.flush()
    found = await blockers(db, world.trigger, creator=world.ctx, paused_for_budget=False)
    assert "routine_changed" in [blocker.code for blocker in found]


async def test_readiness_counts_nothing_when_the_version_cannot_be_read(
    db: AsyncSession, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.routine_readiness import _waiting

    async def unavailable(*_args: object) -> object:
        raise NotFoundError(message="Agent not found")

    monkeypatch.setattr(RoutineAccessService, "offered", unavailable)
    assert await _waiting(db, world.ctx, world.trigger) == 0


# Platform tools


async def test_platform_tools_are_offered_only_acting_as_the_creator(
    db: AsyncSession, world: World
) -> None:
    world.trigger.runs_as_creator = True
    await publish(
        db,
        world,
        world.spec.model_copy(
            update={
                "mcp_servers": [
                    PlatformMcpServerRef(
                        account="platform",
                        approval="writes",
                        allowed_tools=[
                            "list_virtual_tables",
                            "add_virtual_table_record",
                            "invite_member",
                            "publish_inbox_finding",
                        ],
                    )
                ]
            }
        ),
    )
    world.trigger.approved_sources = (
        await RoutineAccessService(db).initial(world.ctx, world.trigger)
    ).model_dump(mode="json")
    await db.flush()
    review = await access(db, world)
    platform = {o.tool_id: o for o in review.tools if isinstance(o, RoutinePlatformToolOption)}
    assert set(platform) == {"list_virtual_tables", "add_virtual_table_record", "invite_member"}
    assert platform["list_virtual_tables"].agent == "free"
    assert platform["invite_member"].agent == "ask" and platform["invite_member"].effect
    assert platform["add_virtual_table_record"].group == "tables"
    await save(
        db,
        world,
        {"kind": "platform", "tool_id": "list_virtual_tables", "setting": "off"},
        {"kind": "platform", "tool_id": "add_virtual_table_record", "setting": "allow"},
    )
    authority = await capture(db, world)
    listing = ToolDefinition(name="agenticos_list_virtual_tables", metadata={PLATFORM_TOOL: True})
    with pytest.raises(AuthorizationError, match="turned off"):
        await authority.action_policy(world.agent.id, world.spec, listing)
    unknown = ToolDefinition(name="agenticos_invented", metadata={PLATFORM_TOOL: True})
    assert authority.tool_key(world.spec, unknown) is None
    world.trigger.runs_as_creator = False
    await db.flush()
    review = await access(db, world)
    assert not [o for o in review.tools if isinstance(o, RoutinePlatformToolOption)]


# The organization's switch


async def test_only_approvals_decide_switches_routine_trust_and_it_is_audited(
    db: AsyncSession, world: World
) -> None:
    service = OrganizationService(db)
    updated = await service.update(
        world.org.id, OrganizationUpdate(routines_may_trust_agent=True), world.ctx.subject_id
    )
    assert updated.routines_may_trust_agent
    (entry,) = await audits(db, "organization.routine_trust_changed")
    assert entry.details == {"from": False, "to": True}
    # Setting it to what it is records nothing.
    await service.update(
        world.org.id, OrganizationUpdate(routines_may_trust_agent=True), world.ctx.subject_id
    )
    assert len(await audits(db, "organization.routine_trust_changed")) == 1
    await become(db, world, OrgRoleName.BUILDER)
    with pytest.raises(AuthorizationError, match="trust"):
        await service.update(
            world.org.id, OrganizationUpdate(routines_may_trust_agent=False), world.ctx.subject_id
        )


async def test_a_disabled_account_offers_no_tool(db: AsyncSession, world: World) -> None:
    connection = await _mail(db, world)
    connection.is_enabled = False
    await db.flush()
    review = await access(db, world)
    assert not [o for o in review.tools if isinstance(o, RoutineMcpToolOption)]
    assert review.unlisted_accounts == []


async def test_the_review_says_when_the_platform_needs_the_creator(
    db: AsyncSession, world: World
) -> None:
    await publish(
        db,
        world,
        world.spec.model_copy(update={"mcp_servers": [PlatformMcpServerRef(account="platform")]}),
    )
    reviewed_sources(world.trigger, spec=world.spec, version_id=world.version.id)
    await db.flush()
    review = await access(db, world)
    assert not review.current and review.review_reason == "platform_identity"


def test_a_ceiling_is_one_snapshot_of_sources_without_tool_settings() -> None:
    from pydantic import ValidationError

    sources = {
        "id": uuid4(),
        "consented_by": uuid4(),
        "reviewed_at": datetime.now(UTC),
        "version_id": uuid4(),
        "scope_hash": "a" * 64,
        "spec_hash": "b" * 64,
    }
    setting = {"capability_id": "sandbox", "tool_id": "execute", "setting": "allow"}
    for ceiling in ({**sources, "tools": [setting]}, {**sources, "approved_ceiling": sources}):
        with pytest.raises(ValidationError, match="one non-nested snapshot"):
            RoutineSourcePolicy.model_validate({**sources, "approved_ceiling": ceiling})


def test_a_project_source_names_its_workspace() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="exact workspace identity"):
        RoutineSourcePolicy.model_validate(
            {
                "id": uuid4(),
                "consented_by": uuid4(),
                "reviewed_at": datetime.now(UTC),
                "version_id": uuid4(),
                "scope_hash": "a" * 64,
                "spec_hash": "b" * 64,
                "project_id": uuid4(),
            }
        )


async def test_the_source_snapshot_is_its_owners_alone(db: AsyncSession, world: World) -> None:
    with pytest.raises(AuthorizationError, match="owner"):
        await RoutineSourceService(db).snapshot(replace(world.ctx, user_id=uuid4()), world.trigger)


async def test_a_remote_agent_whose_credential_is_gone_cannot_be_fingerprinted(
    db: AsyncSession, world: World
) -> None:
    from app.db.models.external_agent import ExternalAgent
    from app.services.routine_sources import external_fingerprint

    remote = ExternalAgent(
        organization_id=world.org.id,
        slug=f"remote-{uuid4()}",
        name="Remote",
        card_url="https://remote.example/card",
        endpoint_url="https://remote.example/rpc",
        card={},
        secret_id=uuid4(),
    )
    with pytest.raises(RoutineSourcesRequired, match="credential"):
        await external_fingerprint(db, remote)


async def test_an_mcp_tool_outside_the_reviewed_account_needs_a_review(
    db: AsyncSession, world: World
) -> None:
    connection = await _mail(db, world)
    authority = await capture(db, world)
    origin = McpToolOrigin(
        connection_id=connection.id,
        identity=McpSourceIdentity(
            endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
            authorization_generation=connection.authorization_generation,
            tool_prefix=tool_prefix(connection.name),
        ),
        tool_id="drop_mail",
    )
    with pytest.raises(RoutineSourcesRequired):
        await authority.action_policy(
            world.agent.id,
            world.spec,
            ToolDefinition(name="mail_drop_mail", metadata={MCP_ORIGIN: origin}),
        )
