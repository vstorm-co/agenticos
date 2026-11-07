"""A responsibility never borrows later accounts, tools or source consent."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, SubagentRef
from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.schemas.routine_sources import RoutineSourceConsent
from app.services.agent_trigger import AgentTriggerService
from app.services.routine_authority import RoutineAuthority
from app.services.routine_sources import (
    RoutineSourceService,
    RoutineSourcesRequired,
    read_policy,
    spec_fingerprint,
)
from app.worker.jobs import FireTrigger
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio


async def world(
    db: AsyncSession, *, mcp: bool = False
) -> tuple[AuthContext, AgentTrigger, AgentSpec, McpConnection | None]:
    user, org = await seed_member(db)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    account = None
    if mcp:
        account = McpConnection(
            id=uuid4(),
            organization_id=org.id,
            created_by_user_id=user.id,
            scope="org",
            purpose="mcp",
            name="Source",
            url="https://tools.example.com",
            auth_type="none",
            is_enabled=True,
            last_tools=[{"name": "read", "description": "Read"}],
        )
        db.add(account)
        await db.flush()
    spec = AgentSpec(
        name="Worker",
        mcp_servers=[]
        if account is None
        else [{"account": "organization", "connection_id": account.id}],
    )
    agent = Agent(
        organization_id=org.id,
        owner_user_id=user.id,
        name="Worker",
        slug=f"worker-{uuid4()}",
        status="published",
    )
    db.add(agent)
    await db.flush()
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
        pinned_version_id=version.id,
        prompt="Check",
        interval_seconds=300,
        next_fire_at=datetime.now(UTC),
        runs_as_creator=True,
    )
    db.add(trigger)
    await db.flush()
    policy = await RoutineSourceService(db).initial(ctx, trigger)
    trigger.approved_sources = policy.model_dump(mode="json")
    await db.flush()
    return ctx, trigger, spec, account


async def test_review_is_metadata_only_and_current(db: AsyncSession):
    ctx, trigger, _, _ = await world(db, mcp=True)
    options = await RoutineSourceService(db).options(ctx, trigger)
    assert options.current and len(options.accounts) == 1 and options.unavailable_sources == []
    policy = read_policy(trigger.approved_sources)
    assert policy.mcp_sources
    assert (
        await RoutineSourceService(db).require_current(ctx, trigger, expected_id=policy.id)
    ).id == policy.id


@pytest.mark.parametrize("change", ["generation", "endpoint", "tools", "disabled", "audience"])
async def test_source_changes_require_review_before_provider_io(db: AsyncSession, change: str):
    ctx, trigger, _, account = await world(db, mcp=True)
    assert account is not None
    policy = read_policy(trigger.approved_sources)
    if change == "generation":
        account.authorization_generation = uuid4()
    elif change == "endpoint":
        account.url = "https://another.example.com"
    elif change == "tools":
        account.last_tools = [*account.last_tools, {"name": "send", "description": "Send"}]
    elif change == "disabled":
        account.is_enabled = False
    else:
        trigger.delivery_mode = "manual"
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await RoutineSourceService(db).require_current(ctx, trigger, expected_id=policy.id)


async def test_model_and_instructions_can_change_but_knowledge_cannot(db: AsyncSession):
    _, _, spec, _ = await world(db)
    assert spec_fingerprint(spec) == spec_fingerprint(
        spec.model_copy(update={"instructions": "Revised", "max_steps": 3})
    )
    assert spec_fingerprint(spec) != spec_fingerprint(
        spec.model_copy(update={"collection_ids": [uuid4()]})
    )


@pytest.mark.parametrize("identity", ["other", "api", "routine", "fallback"])
async def test_only_console_owner_can_review(db: AsyncSession, identity: str):
    ctx, trigger, _, _ = await world(db)
    if identity == "other":
        ctx = replace(ctx, user_id=uuid4())
    elif identity == "api":
        ctx = replace(ctx, api_key_id=uuid4(), key_internal=True)
    elif identity == "routine":
        ctx = replace(ctx, routine_id=trigger.id)
    else:
        ctx = replace(ctx, subject_is_publisher_fallback=True)
    with pytest.raises(AuthorizationError):
        await RoutineSourceService(db).options(ctx, trigger)


async def test_stale_token_cannot_grant_changed_sources(db: AsyncSession):
    ctx, trigger, _, account = await world(db, mcp=True)
    service = RoutineSourceService(db)
    reviewed = await service.options(ctx, trigger)
    assert account is not None
    account.authorization_generation = uuid4()
    await db.flush()
    with pytest.raises(ConflictError):
        await service.replace(
            ctx, trigger, RoutineSourceConsent(review_token=reviewed.review_token)
        )
    fresh = await service.options(ctx, trigger)
    old = read_policy(trigger.approved_sources).id
    await service.replace(ctx, trigger, RoutineSourceConsent(review_token=fresh.review_token))
    assert read_policy(trigger.approved_sources).id != old


async def test_legacy_routine_refuses_without_silent_opt_in(db: AsyncSession):
    ctx, trigger, _, _ = await world(db)
    trigger.approved_sources = None
    await db.flush()
    assert not (await RoutineSourceService(db).options(ctx, trigger)).current
    with pytest.raises(RoutineSourcesRequired):
        await RoutineSourceService(db).require_current(ctx, trigger, expected_id=None)
    assert (
        await AgentTriggerService(db).queue_fire(trigger.id, organization_id=ctx.organization_id)
        is None
    )


async def test_queued_old_review_cannot_borrow_replacement(db: AsyncSession):
    ctx, trigger, _, _ = await world(db)
    old = read_policy(trigger.approved_sources).id
    service = RoutineSourceService(db)
    options = await service.options(ctx, trigger)
    await service.replace(ctx, trigger, RoutineSourceConsent(review_token=options.review_token))
    triggers = AgentTriggerService(db)
    with patch.object(triggers, "fire", new_callable=AsyncMock) as fire:
        await triggers.fire_job(FireTrigger(trigger_id=trigger.id, source_policy_id=old))
        await triggers.fire_job(FireTrigger(trigger_id=trigger.id))
    fire.assert_not_awaited()


async def test_old_review_invalidates_live_authority_and_spec_widening(db: AsyncSession):
    ctx, trigger, spec, _ = await world(db)
    policy = read_policy(trigger.approved_sources)
    authority = await RoutineAuthority.capture(
        db,
        replace(
            ctx,
            routine_id=trigger.id,
            fired_as_creator="schedule",
            routine_source_policy_id=policy.id,
        ),
        agent_id=trigger.agent_id,
        run=None,
    )
    assert authority is not None
    authority.require_spec(spec)
    with pytest.raises(RoutineSourcesRequired):
        authority.require_spec(spec.model_copy(update={"context_ids": [uuid4()]}))
    service = RoutineSourceService(db)
    options = await service.options(ctx, trigger)
    await service.replace(ctx, trigger, RoutineSourceConsent(review_token=options.review_token))
    with pytest.raises(RoutineSourcesRequired):
        await authority.check_in(db, trigger.agent_id)


@pytest.mark.parametrize(
    "inventory", [None, [{"wrong": "field"}], [{"name": "x" * 1001, "description": "Read"}]]
)
async def test_invalid_or_missing_inventory_is_visible_and_never_consented(
    db: AsyncSession, inventory: object
):
    ctx, trigger, _, account = await world(db, mcp=True)
    assert account is not None
    account.last_tools = inventory
    await db.flush()
    service = RoutineSourceService(db)
    offered = await service.options(ctx, trigger)
    assert not offered.current and offered.unavailable_sources
    with pytest.raises(RoutineSourcesRequired):
        await service.initial(ctx, trigger)
    with pytest.raises(ConflictError):
        await service.replace(ctx, trigger, RoutineSourceConsent(review_token=offered.review_token))


async def test_following_version_keeps_sources_for_model_only_publication(db: AsyncSession):
    ctx, trigger, _, _ = await world(db)
    trigger.pinned_version_id = None
    await db.flush()
    service = RoutineSourceService(db)
    trigger.approved_sources = (await service.initial(ctx, trigger)).model_dump(mode="json")
    await db.flush()
    assert (await service.options(ctx, trigger)).current


async def test_missing_input_account_can_be_reviewed_as_unavailable(db: AsyncSession):
    ctx, trigger, _, _ = await world(db)
    # This transient invalid source is never written through the trigger mutation API.
    trigger.connection_id = uuid4()
    with db.no_autoflush:
        offered = await RoutineSourceService(db).options(ctx, trigger)
    assert not offered.current and offered.unavailable_sources == ["event source"]
    trigger.connection_id = None


async def test_input_grant_generation_is_checked_before_continuing(db: AsyncSession):
    from app.services.routine_sources import require_bound_sources

    ctx, trigger, _, account = await world(db, mcp=True)
    assert account is not None
    trigger.connection_id = account.id
    with db.no_autoflush:
        policy = await RoutineSourceService(db).initial(ctx, trigger)
    trigger.connection_id = None
    await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
    account.authorization_generation = uuid4()
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)


async def test_personal_accounts_are_explicit_and_do_not_follow_new_defaults(db: AsyncSession):
    from app.agents.spec import PersonalMcpServerRef
    from app.db.models.agent import AgentVersion

    ctx, trigger, spec, _ = await world(db)
    first = McpConnection(
        scope="user",
        user_id=ctx.subject_id,
        purpose="mcp",
        name="Work",
        catalog_key="github",
        is_default=True,
        url="https://one.example.com",
        is_enabled=True,
        last_tools=[{"name": "read", "description": "Read"}],
    )
    second = McpConnection(
        scope="user",
        user_id=ctx.subject_id,
        purpose="mcp",
        name="Home",
        catalog_key="github",
        url="https://two.example.com",
        is_enabled=True,
        last_tools=first.last_tools,
    )
    db.add_all([first, second])
    await db.flush()
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = spec.model_copy(
        update={"mcp_servers": [PersonalMcpServerRef(account="personal", catalog_key="github")]}
    ).model_dump(mode="json")
    await db.flush()
    service = RoutineSourceService(db)
    policy = await service.initial(ctx, trigger)
    assert policy.mcp_sources[first.id].tool_prefix == "github"
    assert policy.mcp_sources[second.id].tool_prefix == "github_home"
    trigger.approved_sources = policy.model_dump(mode="json")
    first.is_default = False
    await db.flush()
    second.is_default = True
    await db.flush()
    assert not (await service.options(ctx, trigger)).current
    assert policy.mcp_sources[first.id].tool_prefix == "github"
    trigger.runs_as_creator = False
    await db.flush()
    assert not (await service.initial(ctx, trigger)).mcp_sources


async def test_unconnected_personal_source_is_not_silently_approved(db: AsyncSession):
    from app.agents.spec import PersonalMcpServerRef

    ctx, trigger, spec, _ = await world(db)
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = spec.model_copy(
        update={"mcp_servers": [PersonalMcpServerRef(account="personal", catalog_key="github")]}
    ).model_dump(mode="json")
    await db.flush()
    offered = await RoutineSourceService(db).options(ctx, trigger)
    assert offered.unavailable_sources == ["github"]


async def test_tool_allowlists_intersect_and_unreviewed_tools_are_hidden(db: AsyncSession):
    from pydantic_ai.tools import ToolDefinition

    from app.agents.mcp import MCP_ORIGIN, McpToolOrigin
    from app.services.routine_sources import account_identities

    ctx, trigger, spec, account = await world(db, mcp=True)
    assert account is not None
    account.last_tools = [
        {"name": name, "description": name} for name in ("read", "send", "delete")
    ]
    account.allowed_tools = ["read", "send"]
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    constrained = spec.model_copy(
        update={
            "mcp_servers": [
                spec.mcp_servers[0].model_copy(update={"allowed_tools": ["read", "delete"]})
            ]
        }
    )
    version.spec = constrained.model_dump(mode="json")
    await db.flush()
    policy = await RoutineSourceService(db).initial(ctx, trigger)
    trigger.approved_sources = policy.model_dump(mode="json")
    await db.flush()
    authority = await RoutineAuthority.capture(
        db,
        replace(
            ctx,
            routine_id=trigger.id,
            fired_as_creator="schedule",
            routine_source_policy_id=policy.id,
        ),
        agent_id=trigger.agent_id,
        run=None,
    )
    assert authority is not None
    assert policy.mcp_sources[account.id].tool_ids == ("read",)
    identity = account_identities(policy)[account.id]
    assert authority.allows_tool(ToolDefinition(name="internal"))
    assert authority.allows_tool(
        ToolDefinition(
            name="read", metadata={MCP_ORIGIN: McpToolOrigin(account.id, identity, "read")}
        )
    )
    assert not authority.allows_tool(
        ToolDefinition(
            name="send", metadata={MCP_ORIGIN: McpToolOrigin(account.id, identity, "send")}
        )
    )


async def test_remote_agent_card_and_endpoint_cannot_retarget_a_routine(db: AsyncSession):
    from app.agents.spec import ExternalAgentRef
    from app.db.models.external_agent import ExternalAgent
    from app.services.routine_sources import require_bound_sources

    ctx, trigger, spec, _ = await world(db)
    remote = ExternalAgent(
        organization_id=ctx.organization_id,
        slug=f"remote-{uuid4()}",
        name="Remote",
        card_url="https://remote.example.com/card",
        endpoint_url="https://remote.example.com/rpc",
        card={"name": "Remote"},
    )
    db.add(remote)
    await db.flush()
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = spec.model_copy(
        update={"external_agents": [ExternalAgentRef(external_agent_id=remote.id)]}
    ).model_dump(mode="json")
    await db.flush()
    service = RoutineSourceService(db)
    policy = await service.initial(ctx, trigger)
    await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
    remote.endpoint_url = "https://another.example.com/rpc"
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
    await db.delete(remote)
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
    offered = await service.options(ctx, trigger)
    assert offered.unavailable_sources


async def test_source_metadata_export_and_erasure_follow_the_exact_owner(db: AsyncSession):
    from app.db.models.agent_run import AgentRun
    from app.repositories import personal_data_repo

    ctx, trigger, _, _ = await world(db)
    foreign_ctx, foreign_trigger, _, _ = await world(db)
    run = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=trigger.agent_id,
        started_at=datetime.now(UTC),
        user_id=ctx.user_id,
        routine_policy={"approved_sources": trigger.approved_sources},
    )
    foreign_run = AgentRun(
        organization_id=foreign_ctx.organization_id,
        agent_id=foreign_trigger.agent_id,
        started_at=datetime.now(UTC),
        user_id=foreign_ctx.user_id,
        routine_policy={"approved_sources": foreign_trigger.approved_sources},
    )
    db.add_all([run, foreign_run])
    await db.flush()
    assert [row.id for row in await personal_data_repo.routine_sources_of(db, ctx.subject_id)] == [
        trigger.id
    ]
    assert await personal_data_repo.routine_source_export_size(db, ctx.subject_id) > 0
    assert await personal_data_repo.routine_source_export_size(db, uuid4()) == 0
    from app.schemas.personal_data import RoutineSourceExport

    before = await personal_data_repo.routine_source_export_size(db, ctx.subject_id)
    consent = {
        "id": str(uuid4()),
        "consented_by": str(ctx.subject_id),
        "version_id": str(uuid4()),
        "intent_hash": "a" * 64,
        "instructions_hash": "b" * 64,
        "capability_id": "web_fetch",
        "tool_id": "web_fetch",
    }
    trigger.action_consents = [consent]
    await db.flush()
    exported = RoutineSourceExport.model_validate(trigger)
    assert exported.action_consents[0].consented_by == ctx.subject_id
    assert await personal_data_repo.routine_source_export_size(db, ctx.subject_id) > before + 200
    await personal_data_repo.purge_routine_authority(db, ctx.subject_id)
    await db.refresh(trigger)
    await db.refresh(run)
    await db.refresh(foreign_trigger)
    await db.refresh(foreign_run)
    assert trigger.approved_sources is None and run.routine_policy is None
    assert foreign_trigger.approved_sources is not None and foreign_run.routine_policy is not None


async def test_review_follows_published_delegate_authority_without_a_new_direct_grant(
    db: AsyncSession,
):
    from app.agents.spec import SubagentRef
    from app.core.exceptions import NotFoundError
    from app.core.permissions import Perm
    from app.db.models.resource_grant import ResourceGrant
    from app.db.models.user import User
    from app.services.agent_registry import AgentRegistryService

    ctx, trigger, spec, account = await world(db, mcp=True)
    assert account is not None
    owner = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(owner)
    await db.flush()
    child = Agent(
        organization_id=ctx.organization_id,
        owner_user_id=owner.id,
        name="Delegate",
        slug=f"child-{uuid4()}",
        status="published",
        visibility="private",
    )
    db.add(child)
    await db.flush()
    child_spec = AgentSpec(name="Delegate", mcp_servers=spec.mcp_servers)
    child_version = AgentVersion(
        agent_id=child.id,
        organization_id=ctx.organization_id,
        version=1,
        spec=child_spec.model_dump(mode="json"),
    )
    db.add(child_version)
    await db.flush()
    child.current_version_id = child_version.id
    root_version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert root_version is not None
    root_version.spec = spec.model_copy(
        update={
            "mcp_servers": [],
            "subagents": [SubagentRef(agent_id=child.id, agent_version_id=child_version.id)],
        }
    ).model_dump(mode="json")
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            resource_type="agent",
            resource_id=trigger.agent_id,
            subject_user_id=ctx.user_id,
            level="use",
        )
    )
    await db.flush()
    viewer = replace(ctx, role="viewer")
    with pytest.raises((AuthorizationError, NotFoundError)):
        await AgentRegistryService(db).get(viewer, child.id, perm=Perm.AGENTS_RUN)
    reviewed = await RoutineSourceService(db).initial(viewer, trigger)
    assert account.id in reviewed.mcp_sources and reviewed.root_mcp_ids == ()
    assert any(
        "Delegate" in resource
        for resource in (await RoutineSourceService(db).options(viewer, trigger)).resources
    )


async def test_review_refuses_a_withdrawn_pinned_delegate(db: AsyncSession):
    from app.agents.spec import SubagentRef

    ctx, trigger, spec, _ = await world(db)
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = spec.model_copy(
        update={"subagents": [SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())]}
    ).model_dump(mode="json")
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await RoutineSourceService(db).initial(ctx, trigger)


async def test_deleted_parent_and_stale_expected_identity_refuse_consent(db: AsyncSession):
    ctx, trigger, _, _ = await world(db)
    service = RoutineSourceService(db)
    offered = await service.options(ctx, trigger)
    with pytest.raises(RoutineSourcesRequired):
        await service.require_current(ctx, trigger, expected_id=uuid4())
    await db.delete(trigger)
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await service.replace(ctx, trigger, RoutineSourceConsent(review_token=offered.review_token))


def test_input_identity_cannot_be_half_present():
    with pytest.raises(RoutineSourcesRequired):
        read_policy(
            {
                "id": uuid4(),
                "consented_by": uuid4(),
                "reviewed_at": datetime.now(UTC),
                "version_id": uuid4(),
                "scope_hash": "a" * 64,
                "spec_hash": "b" * 64,
                "input_connection_id": uuid4(),
            }
        )


@pytest.mark.parametrize("kind", ["mcp", "remote", "delegate"])
async def test_source_review_is_bounded_before_provider_io(db: AsyncSession, kind: str):
    from app.agents.spec import ExternalAgentRef, OrgMcpServerRef, SubagentRef
    from app.db.models.external_agent import ExternalAgent

    ctx, trigger, spec, _ = await world(db)
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    if kind == "mcp":
        accounts = [
            McpConnection(
                scope="org",
                purpose="mcp",
                organization_id=ctx.organization_id,
                name=f"Source {index}",
                url=f"https://source{index}.example.com",
                is_enabled=True,
                last_tools=[{"name": "read", "description": "Read"}],
            )
            for index in range(101)
        ]
        db.add_all(accounts)
        await db.flush()
        updated = spec.model_copy(
            update={
                "mcp_servers": [OrgMcpServerRef(connection_id=account.id) for account in accounts]
            }
        )
    elif kind == "remote":
        remotes = [
            ExternalAgent(
                organization_id=ctx.organization_id,
                slug=f"remote{index}",
                name=f"Remote {index}",
                card_url=f"https://remote{index}.example.com/card",
                endpoint_url=f"https://remote{index}.example.com/rpc",
                card={},
            )
            for index in range(101)
        ]
        db.add_all(remotes)
        await db.flush()
        updated = spec.model_copy(
            update={
                "external_agents": [
                    ExternalAgentRef(external_agent_id=remote.id) for remote in remotes
                ]
            }
        )
    else:
        children = [
            Agent(
                organization_id=ctx.organization_id,
                owner_user_id=ctx.user_id,
                name=f"Child {index}",
                slug=f"child{index}",
                status="published",
            )
            for index in range(65)
        ]
        db.add_all(children)
        await db.flush()
        versions = [
            AgentVersion(
                organization_id=ctx.organization_id,
                agent_id=child.id,
                version=1,
                spec=spec.model_dump(mode="json"),
            )
            for child in children
        ]
        db.add_all(versions)
        await db.flush()
        updated = spec.model_copy(
            update={
                "subagents": [
                    SubagentRef(agent_id=child.id, agent_version_id=child_version.id)
                    for child, child_version in zip(children, versions, strict=True)
                ]
            }
        )
    version.spec = updated.model_dump(mode="json")
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await RoutineSourceService(db).initial(ctx, trigger)


async def test_shared_delegate_sources_are_unioned_and_cycles_do_not_expand_review(
    db: AsyncSession,
):
    from app.agents.spec import SubagentRef

    ctx, trigger, spec, account = await world(db, mcp=True)
    assert account is not None
    child = Agent(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="Child",
        slug=f"child-{uuid4()}",
        status="published",
    )
    db.add(child)
    await db.flush()
    child_version = AgentVersion(
        organization_id=ctx.organization_id,
        agent_id=child.id,
        version=1,
        spec=spec.model_dump(mode="json"),
    )
    db.add(child_version)
    await db.flush()
    reference = SubagentRef(agent_id=child.id, agent_version_id=child_version.id)
    child_version.spec = spec.model_copy(update={"subagents": [reference]}).model_dump(mode="json")
    root_version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert root_version is not None
    root_version.spec = spec.model_copy(update={"subagents": [reference]}).model_dump(mode="json")
    await db.flush()
    policy = await RoutineSourceService(db).initial(ctx, trigger)
    assert policy.mcp_sources[account.id].tool_ids == ("read",)
    assert len(policy.mcp_sources) == 1


async def test_mail_poll_admission_does_not_borrow_later_review_or_another_account(
    db: AsyncSession,
):
    ctx, trigger, _, _ = await world(db)
    grant = McpConnection(
        scope="org",
        purpose="portal",
        portal_key="google",
        organization_id=ctx.organization_id,
        name="Mailbox",
        url="https://mail.example.com",
        is_enabled=True,
    )
    db.add(grant)
    await db.flush()
    trigger.trigger_type = "event"
    trigger.event_source = "gmail"
    trigger.connection_id = grant.id
    trigger.portal_key = "google"
    trigger.delivery_mode = "polling"
    trigger.next_fire_at = None
    trigger.interval_seconds = None
    await db.flush()
    service = RoutineSourceService(db)
    policy = await service.initial(ctx, trigger)
    trigger.approved_sources = policy.model_dump(mode="json")
    await db.flush()
    triggers = AgentTriggerService(db)
    assert await triggers.polled_source_admissions(
        organization_id=ctx.organization_id, event_source="gmail", connection=grant
    ) == {trigger.id: policy.id}
    other = McpConnection(
        id=uuid4(),
        scope="org",
        purpose="portal",
        organization_id=ctx.organization_id,
        name="Other",
        url="https://other.example.com",
        is_enabled=True,
    )
    assert not await triggers.polled_source_admissions(
        organization_id=ctx.organization_id, event_source="gmail", connection=other
    )
    offered = await service.options(ctx, trigger)
    await service.replace(ctx, trigger, RoutineSourceConsent(review_token=offered.review_token))
    assert (
        await triggers.queue_fire(
            trigger.id,
            organization_id=ctx.organization_id,
            event_context="Old account event",
            source_policy_id=policy.id,
        )
        is None
    )
    grant.authorization_generation = uuid4()
    await db.flush()
    assert not await triggers.polled_source_admissions(
        organization_id=ctx.organization_id, event_source="gmail", connection=grant
    )


async def test_remote_source_review_fences_credential_rotation_but_not_label_changes(
    db: AsyncSession,
):
    from app.agents.spec import ExternalAgentRef
    from app.core.secret_kinds import ApiKeySecret
    from app.db.models.external_agent import ExternalAgent
    from app.services.organization_secret import OrganizationSecretService
    from app.services.routine_sources import require_bound_sources

    ctx, trigger, spec, _ = await world(db)
    secrets = OrganizationSecretService(db)
    secret = await secrets.create(
        ctx, name="Remote bearer", value=ApiKeySecret(api_key="test-first-account"), purpose="a2a"
    )
    remote = ExternalAgent(
        organization_id=ctx.organization_id,
        slug=uuid4().hex,
        name="Remote",
        card_url="https://remote.example/card",
        endpoint_url="https://remote.example/rpc",
        card={},
        secret_id=secret.id,
    )
    db.add(remote)
    await db.flush()
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = spec.model_copy(
        update={"external_agents": [ExternalAgentRef(external_agent_id=remote.id)]}
    ).model_dump(mode="json")
    await db.flush()
    policy = await RoutineSourceService(db).initial(ctx, trigger)
    await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
    generation = secret.authorization_generation
    await secrets.update(ctx, secret.id, name="Renamed bearer")
    assert secret.authorization_generation == generation
    await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
    await secrets.update(ctx, secret.id, value=ApiKeySecret(api_key="test-replacement-account"))
    assert secret.authorization_generation != generation
    with pytest.raises(RoutineSourcesRequired):
        await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
    reviewed = await RoutineSourceService(db).initial(ctx, trigger)
    await require_bound_sources(db, organization_id=ctx.organization_id, policy=reviewed)


@pytest.mark.security
async def test_budgeted_event_fires_share_one_worker_concurrency_key(db: AsyncSession):
    from decimal import Decimal

    from sqlalchemy import select

    from app.db.models.background_job import BackgroundJob

    ctx, trigger, _, _ = await world(db)
    trigger.monthly_budget_usd = Decimal("1")
    await db.flush()
    service = AgentTriggerService(db)
    first = await service.queue_fire(
        trigger.id, organization_id=ctx.organization_id, event_context="first"
    )
    second = await service.queue_fire(
        trigger.id, organization_id=ctx.organization_id, event_context="second"
    )
    jobs = list(
        await db.scalars(select(BackgroundJob).where(BackgroundJob.id.in_([first, second])))
    )
    assert len(jobs) == 2 and all(
        job.concurrency_key == f"routine-budget:{trigger.id}" for job in jobs
    )


@pytest.mark.security
async def test_mirage_secret_generation_is_part_of_source_consent(db: AsyncSession):
    from app.db.models.organization_secret import OrganizationSecret

    ctx, trigger, spec, _ = await world(db)
    secret = OrganizationSecret(
        organization_id=ctx.organization_id,
        name="Terminal storage",
        kind="api_key",
        sealed_secret="sealed",
        key_version=1,
        created_by_user_id=ctx.user_id,
    )
    db.add(secret)
    await db.flush()
    spec = spec.model_copy(
        update={
            "capabilities": [
                {
                    "id": "mirage",
                    "config": {
                        "mounts": [
                            {
                                "path": "/storage/",
                                "backend": "postgres",
                                "secrets": {"dsn": str(secret.id)},
                            }
                        ]
                    },
                }
            ]
        }
    )
    # Validate the same stored representation the runner reads.
    spec = AgentSpec.model_validate(spec.model_dump())
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = spec.model_dump(mode="json")
    await db.flush()
    policy = await RoutineSourceService(db).initial(ctx, trigger)
    assert policy.secret_sources == {secret.id: secret.authorization_generation}
    trigger.approved_sources = policy.model_dump(mode="json")
    await db.flush()
    secret.authorization_generation = uuid4()
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        await RoutineSourceService(db).require_current(ctx, trigger, expected_id=policy.id)


@pytest.mark.parametrize("owner", ["organization", "personal"])
@pytest.mark.parametrize(
    "state", ["active", "missing", "unattributed", "disabled", "rotated_client"]
)
async def test_terminal_account_source_review_fences_exact_owner_and_client_generation(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, owner: str, state: str
) -> None:
    from app.db.models.organization_secret import OrganizationSecret
    from app.services import mcp_connection
    from app.services.routine_sources import require_bound_sources

    ctx, trigger, spec, _ = await world(db)
    secret = OrganizationSecret(
        organization_id=ctx.organization_id,
        name="Google client",
        kind="api_key",
        sealed_secret="sealed",
        key_version=1,
        created_by_user_id=ctx.user_id,
    )
    db.add(secret)
    await db.flush()
    account = McpConnection(
        id=uuid4(),
        organization_id=ctx.organization_id if owner == "organization" else None,
        user_id=ctx.user_id if owner == "personal" else None,
        scope="org" if owner == "organization" else "user",
        purpose="account",
        catalog_key="google",
        name="google-terminal",
        url="https://accounts.google.com",
        is_enabled=state != "disabled",
        oauth_payload="sealed",
        account_source_organization_id=ctx.organization_id,
    )
    if state != "missing":
        db.add(account)
        await db.flush()
    client = (
        ctx.organization_id,
        secret.id,
        uuid4() if state == "rotated_client" else secret.authorization_generation,
    )
    monkeypatch.setattr(
        mcp_connection,
        "account_client_identity",
        lambda _account: None if state == "unattributed" else client,
    )
    binding = {"kind": owner}
    if owner == "organization":
        binding["connection_id"] = str(account.id)
    stored = spec.model_dump(mode="json")
    stored["capabilities"] = [
        {
            "id": "mirage",
            "config": {"mounts": [{"path": "/mail/", "backend": "gmail", "account": binding}]},
        }
    ]
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = AgentSpec.model_validate(stored).model_dump(mode="json")
    await db.flush()
    service = RoutineSourceService(db)
    review = await service.options(ctx, trigger)
    if state != "active":
        assert review.unavailable_sources
        with pytest.raises(RoutineSourcesRequired):
            await service.initial(ctx, trigger)
    else:
        policy = await service.initial(ctx, trigger)
        assert policy.mirage_accounts == {account.id: account.authorization_generation}
        assert policy.secret_sources == {secret.id: secret.authorization_generation}
        await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)
        account.authorization_generation = uuid4()
        await db.flush()
        with pytest.raises(RoutineSourcesRequired):
            await require_bound_sources(db, organization_id=ctx.organization_id, policy=policy)


@pytest.mark.security
@pytest.mark.parametrize(
    "source",
    ["credentials", "disabled_phone", "missing_remote", "missing_credential", "missing_phone"],
)
async def test_source_review_bounds_provider_inventory_without_connecting(db, monkeypatch, source):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.repositories import channel_bot_repo, organization_secret_repo, telephony
    from app.services import routine_sources

    ctx, trigger, spec, _ = await world(db)
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    if source == "credentials":

        def mounted():
            return AgentSpec(
                name="Worker",
                capabilities=[
                    {
                        "id": "mirage",
                        "config": {
                            "mounts": [
                                {
                                    "path": f"/code{i}/",
                                    "backend": "github",
                                    "options": {"owner": "o", "repo": "r"},
                                    "secrets": {"token": str(uuid4())},
                                }
                                for i in range(10)
                            ]
                        },
                    }
                ],
            )

        refs = []
        for _ in range(10):
            child = Agent(
                organization_id=ctx.organization_id,
                owner_user_id=ctx.user_id,
                name="Delegate",
                slug=f"delegate-{uuid4()}",
            )
            db.add(child)
            await db.flush()
            child_version = AgentVersion(
                agent_id=child.id,
                organization_id=ctx.organization_id,
                version=1,
                spec=mounted().model_dump(mode="json"),
            )
            db.add(child_version)
            await db.flush()
            refs.append({"agent_id": child.id, "agent_version_id": child_version.id})
        spec = mounted().model_copy(
            update={"subagents": [SubagentRef.model_validate(ref) for ref in refs]}
        )
        monkeypatch.setattr(
            organization_secret_repo, "authorization_generation", AsyncMock(return_value=uuid4())
        )
    elif source == "missing_credential":
        spec = AgentSpec(
            name="Worker",
            capabilities=[
                {
                    "id": "mirage",
                    "config": {
                        "mounts": [
                            {
                                "path": "/code/",
                                "backend": "github",
                                "options": {"owner": "o", "repo": "r"},
                                "secrets": {"token": str(uuid4())},
                            }
                        ]
                    },
                }
            ],
        )
        monkeypatch.setattr(
            organization_secret_repo, "authorization_generation", AsyncMock(return_value=None)
        )
    elif source == "missing_phone":
        spec = AgentSpec(
            name="Worker",
            capabilities=[{"id": "phone_calls", "config": {"endpoint_id": str(uuid4())}}],
        )
        monkeypatch.setattr(telephony, "endpoint", AsyncMock(return_value=None))
    elif source in {"phones", "disabled_phone"}:
        spec = AgentSpec(
            name="Worker",
            capabilities=[
                {
                    "id": "phone_calls",
                    "enabled": source == "phones",
                    "config": {"endpoint_id": str(uuid4())},
                }
                for _ in range(101 if source == "phones" else 1)
            ],
        )
        bot = SimpleNamespace(is_active=True, authorization_generation=uuid4())

        async def endpoint(_db, identifier, **kwargs):
            return SimpleNamespace(
                id=identifier,
                enabled=True,
                bot_id=uuid4(),
                bot_generation=bot.authorization_generation,
            )

        monkeypatch.setattr(telephony, "endpoint", endpoint)
        monkeypatch.setattr(channel_bot_repo, "get_for_org", AsyncMock(return_value=bot))
        monkeypatch.setattr(
            "app.services.telephony.policy.endpoint_fingerprint", lambda *args: "reviewed"
        )
    else:
        spec = AgentSpec(name="Worker", external_agents=[{"external_agent_id": str(uuid4())}])
        monkeypatch.setattr(routine_sources.external_repo, "get", AsyncMock(return_value=None))
    version.spec = spec.model_dump(mode="json")
    await db.flush()
    if source in {"credentials", "phones"}:
        with pytest.raises(RoutineSourcesRequired):
            await RoutineSourceService(db)._review(ctx, trigger)
    else:
        reviewed = await RoutineSourceService(db)._review(ctx, trigger)
        assert bool(reviewed.unavailable) is (source != "disabled_phone")
