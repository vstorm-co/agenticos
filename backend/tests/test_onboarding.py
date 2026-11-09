"""Start readiness is personal, tenant-scoped and independent of tour/demo state."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_repo, member_repo, onboarding_repo, organization_repo, user_repo
from app.schemas.agent import AgentRead
from app.schemas.onboarding import OnboardingUpdate
from app.services.agent_registry import AgentRegistryService
from app.services.model_profile import ModelProfileService
from app.services.onboarding import OnboardingService
from app.services.shipped_agents import ShippedAgentService

pytestmark = pytest.mark.anyio


StartFixture = tuple[AuthContext, OrganizationMember, AsyncMock, OnboardingService]


@pytest.fixture
def start(monkeypatch: pytest.MonkeyPatch) -> StartFixture:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    member = OrganizationMember(
        user_id=ctx.subject_id,
        organization_id=ctx.organization_id,
        role="owner",
        joined_at=datetime.now(UTC) - timedelta(days=1),
    )
    org = Organization(
        id=ctx.organization_id,
        name="Northwind",
        slug="northwind",
        created_by_user_id=ctx.subject_id,
    )
    db = AsyncMock()
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=member))
    monkeypatch.setattr(member_repo, "get", AsyncMock(return_value=member))
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=org))
    monkeypatch.setattr(organization_repo, "get_by_id_for_update", AsyncMock(return_value=org))
    monkeypatch.setattr(member_repo, "first_owner_id", AsyncMock(return_value=ctx.subject_id))
    monkeypatch.setattr(
        user_repo, "get_by_id", AsyncMock(return_value=User(email="owner@example.com"))
    )
    monkeypatch.setattr(onboarding_repo, "latest_result", AsyncMock(return_value=None))
    monkeypatch.setattr(onboarding_repo, "has_activity", AsyncMock(return_value=False))
    monkeypatch.setattr(AgentRegistryService, "list_agents", AsyncMock(return_value=([], 0)))
    monkeypatch.setattr(ShippedAgentService, "setup_candidate", AsyncMock(return_value=None))
    return ctx, member, db, OnboardingService(db)


async def test_demo_goal_and_dismissal_do_not_claim_a_result(start: StartFixture) -> None:
    ctx, member, db, service = start
    result = await service.update(ctx, OnboardingUpdate(goal="document", dismissed=True))
    assert result.goal == "document" and result.dismissed and not result.has_result
    assert not result.completed
    assert result.snoozed_until == member.onboarding_dismissed_at + timedelta(days=1)
    assert member.onboarding_dismissed_at.tzinfo is UTC
    db.flush.assert_awaited()
    await service.update(ctx, OnboardingUpdate(dismissed=False))
    assert member.onboarding_goal == "document" and member.onboarding_dismissed_at is None
    await service.update(ctx, OnboardingUpdate(goal=None))
    assert member.onboarding_goal is None


async def test_empty_patch_preserves_both_preferences(start: StartFixture) -> None:
    ctx, member, _, service = start
    member.onboarding_goal = "meeting"
    member.onboarding_dismissed_at = datetime.now(UTC)
    result = await service.update(ctx, OnboardingUpdate())
    assert result.goal == "meeting" and result.dismissed
    result = await service.update(ctx, OnboardingUpdate(goal=None, dismissed=None))
    assert result.goal is None and result.dismissed


async def test_success_comes_only_from_a_completed_run_and_returns_its_location(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    run = AgentRun(conversation_id=uuid4(), ended_at=datetime.now(UTC))
    monkeypatch.setattr(onboarding_repo, "latest_result", AsyncMock(return_value=run))
    result = await service.state(ctx)
    assert result.has_result and result.latest_conversation_id == run.conversation_id
    assert not result.completed
    assert result.latest_completed_at == run.ended_at
    assert result.support_email == "owner@example.com"


async def test_runnable_grants_are_used_and_all_pages_are_read(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    allowed = AgentRead(
        id=uuid4(),
        name="Shared",
        slug="shared",
        status="published",
        visibility="org",
        can_run=True,
        categories=[],
        tags=[],
        created_at=datetime.now(UTC),
    )
    denied = allowed.model_copy(update={"id": uuid4(), "can_run": False})
    draft = allowed.model_copy(update={"id": uuid4(), "status": "draft"})
    monkeypatch.setattr(
        AgentRegistryService,
        "list_agents",
        AsyncMock(side_effect=[([denied, draft], 3), ([allowed], 3)]),
    )
    result = await service.state(ctx)
    assert [item.id for item in result.agents] == [allowed.id]
    assert AgentRegistryService.list_agents.await_args_list[1].kwargs["skip"] == 2


async def test_empty_page_cannot_loop_forever(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    monkeypatch.setattr(AgentRegistryService, "list_agents", AsyncMock(return_value=([], 100)))
    assert not (await service.state(ctx)).agents


async def test_no_owner_does_not_invent_a_contact(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    monkeypatch.setattr(member_repo, "first_owner_id", AsyncMock(return_value=None))
    assert (await service.state(ctx)).support_email is None


@pytest.mark.parametrize("target", ["member", "organization", "locked_member"])
async def test_missing_membership_or_organization_refuses_the_request(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    ctx, _, _, service = start
    if target == "member":
        monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=None))
    elif target == "organization":
        monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=None))
    else:
        monkeypatch.setattr(member_repo, "get", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await service.update(ctx, OnboardingUpdate(goal="meeting"))


async def test_anonymous_context_cannot_save_personal_progress(start: StartFixture) -> None:
    ctx, _, _, service = start
    with pytest.raises(AuthorizationError):
        await service.state(AuthContext.anonymous(organization_id=ctx.organization_id))


async def test_member_cannot_prepare_a_shared_agent(start: StartFixture) -> None:
    ctx, _, _, service = start
    member = AuthContext(
        user_id=ctx.subject_id, organization_id=ctx.organization_id, role=OrgRoleName.MEMBER
    )
    with pytest.raises(AuthorizationError):
        await service.prepare(member, uuid4())
    state = await service.state(member)
    assert not state.can_prepare and not state.can_configure_model


async def test_preparation_refuses_a_foreign_or_personal_model(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    monkeypatch.setattr(ModelProfileService, "list_profiles", AsyncMock(return_value=[]))
    with pytest.raises(BadRequestError):
        await service.prepare(ctx, uuid4())


async def test_preparation_is_text_only_and_uses_normal_publication(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    profile = SimpleNamespace(id=uuid4())
    agent = Agent(id=uuid4(), name="Getting started")
    monkeypatch.setattr(ModelProfileService, "list_profiles", AsyncMock(return_value=[profile]))
    monkeypatch.setattr(
        "app.services.onboarding.choosable_for_others", lambda _profile, _profiles: True
    )
    monkeypatch.setattr(agent_repo, "get_by_slug", AsyncMock(return_value=None))
    monkeypatch.setattr(AgentRegistryService, "create", AsyncMock(return_value=agent))
    monkeypatch.setattr(AgentRegistryService, "publish", AsyncMock())
    result = await service.prepare(ctx, profile.id)
    spec = AgentRegistryService.create.await_args.args[1]
    assert result.id == agent.id
    assert spec.capabilities == [] and spec.mcp_servers == [] and spec.skill_ids == []
    assert spec.model_profile_id == profile.id and spec.budget.monthly_usd == 5
    AgentRegistryService.publish.assert_awaited_once_with(ctx, agent.id, note="Prepare first task")


async def test_repeated_preparation_never_edits_an_existing_draft(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    profile = SimpleNamespace(id=uuid4())
    existing = Agent(id=uuid4(), name="Existing")
    monkeypatch.setattr(ModelProfileService, "list_profiles", AsyncMock(return_value=[profile]))
    monkeypatch.setattr(
        "app.services.onboarding.choosable_for_others", lambda _profile, _profiles: True
    )
    monkeypatch.setattr(agent_repo, "get_by_slug", AsyncMock(return_value=existing))
    monkeypatch.setattr(
        AgentRegistryService,
        "get_runnable_spec",
        AsyncMock(side_effect=BadRequestError(message="Publish this draft first", details={})),
    )
    with pytest.raises(BadRequestError, match="Publish this draft first"):
        await service.prepare(ctx, profile.id)
    monkeypatch.setattr(
        AgentRegistryService,
        "get_runnable_spec",
        AsyncMock(return_value=(existing, SimpleNamespace(model_profile_id=profile.id), uuid4())),
    )
    assert (await service.prepare(ctx, profile.id)).id == existing.id


async def test_preparation_rechecks_the_organization_under_lock(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    profile = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(ModelProfileService, "list_profiles", AsyncMock(return_value=[profile]))
    monkeypatch.setattr(
        "app.services.onboarding.choosable_for_others", lambda _profile, _profiles: True
    )
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await service.prepare(ctx, profile.id)


async def test_result_query_is_scoped_to_real_personal_web_chats() -> None:
    db = AsyncMock()
    response = MagicMock()
    response.scalar_one_or_none.return_value = None
    db.execute.return_value = response
    org, user = uuid4(), uuid4()
    assert await onboarding_repo.latest_result(db, organization_id=org, user_id=user) is None
    compiled = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    values = list(compiled.params.values())
    assert org in values and user in values and "web" in values and "completed" in values
    assert "initiated_by_publisher_fallback IS false" in str(compiled)
    assert "conversations.user_id" in str(compiled)


def test_progress_cannot_inject_a_fake_success_or_unbounded_goal() -> None:
    for data in [{"has_result": True}, {"goal": "invented"}, {"dismissed": "maybe"}]:
        with pytest.raises(ValidationError):
            OnboardingUpdate.model_validate(data)


async def test_member_preview_never_impersonates_or_discloses_private_agent_names(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, member, _, service = start
    target_id = uuid4()
    target = OrganizationMember(
        user_id=target_id, organization_id=ctx.organization_id, role="member"
    )
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(side_effect=[member, target]))
    monkeypatch.setattr(
        user_repo, "get_by_id", AsyncMock(return_value=User(id=target_id, is_app_admin=False))
    )
    common = AgentRead(
        id=uuid4(),
        name="Common",
        slug="common",
        status="published",
        visibility="org",
        can_run=True,
        categories=[],
        tags=[],
        created_at=datetime.now(UTC),
    )
    private = common.model_copy(update={"id": uuid4(), "name": "Private target agent"})
    monkeypatch.setattr(
        AgentRegistryService,
        "list_agents",
        AsyncMock(side_effect=[([common], 1), ([common, private], 2)]),
    )
    result = await service.preview_member(ctx, target_id)
    assert result.model_dump() == {"has_common_agent": True}
    calls = AgentRegistryService.list_agents.await_args_list
    assert calls[1].args[0].user_id == target_id
    assert calls[1].args[0].role == "member"
    member_repo.get_active.assert_any_await(
        service.db, organization_id=ctx.organization_id, user_id=target_id
    )


async def test_preview_rejects_non_managers_and_foreign_or_removed_members(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, member, _, service = start
    caller = AuthContext(user_id=ctx.subject_id, organization_id=ctx.organization_id, role="member")
    with pytest.raises(AuthorizationError):
        await service.preview_member(caller, uuid4())
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(side_effect=[member, None]))
    with pytest.raises(NotFoundError):
        await service.preview_member(ctx, uuid4())
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=member))
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await service.preview_member(ctx, uuid4())


async def test_repeated_preparation_cannot_claim_to_change_an_existing_model(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    profile = SimpleNamespace(id=uuid4())
    existing = Agent(id=uuid4(), name="Existing")
    monkeypatch.setattr(ModelProfileService, "list_profiles", AsyncMock(return_value=[profile]))
    monkeypatch.setattr(
        "app.services.onboarding.choosable_for_others", lambda _profile, _profiles: True
    )
    monkeypatch.setattr(agent_repo, "get_by_slug", AsyncMock(return_value=existing))
    monkeypatch.setattr(
        AgentRegistryService,
        "get_runnable_spec",
        AsyncMock(return_value=(existing, SimpleNamespace(model_profile_id=uuid4()), uuid4())),
    )
    with pytest.raises(BadRequestError, match="another model"):
        await service.prepare(ctx, profile.id)


async def test_existing_chat_activity_suppresses_a_new_start_without_claiming_success(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    activity = AsyncMock(return_value=True)
    monkeypatch.setattr(onboarding_repo, "has_activity", activity)
    result = await service.state(ctx)
    assert result.has_activity and not result.has_result
    assert result.latest_conversation_id is None
    activity.assert_awaited_once_with(
        service.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
    )


@pytest.mark.security
@pytest.mark.parametrize("present", [False, True])
async def test_activity_query_is_personal_and_tenant_scoped(present: bool) -> None:
    db = AsyncMock()
    db.scalar.return_value = present
    org, user = uuid4(), uuid4()
    assert await onboarding_repo.has_activity(db, organization_id=org, user_id=user) is present
    compiled = db.scalar.await_args.args[0].compile(dialect=postgresql.dialect())
    assert org in compiled.params.values() and user in compiled.params.values()
    assert "user" in compiled.params.values()
    assert "messages.conversation_id = conversations.id" in str(compiled)
    assert "conversations.organization_id" in str(compiled)


async def test_legacy_onboarding_completion_is_respected_without_claiming_a_run(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    person = User(email="owner@example.com", onboarding_completed_at=datetime.now(UTC))
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=person))
    result = await service.state(ctx)
    assert (
        result.dismissed and result.completed and not result.has_result and not result.has_activity
    )


@pytest.mark.parametrize(
    "elapsed,hidden",
    [
        (timedelta(hours=23, minutes=59), True),
        (timedelta(days=1), False),
        (timedelta(days=2), False),
    ],
)
async def test_closing_the_offer_only_snoozes_it_for_one_day(
    start: StartFixture, elapsed: timedelta, hidden: bool
) -> None:
    ctx, member, _, service = start
    member.onboarding_dismissed_at = datetime.now(UTC) - elapsed
    result = await service.state(ctx)
    assert result.dismissed is hidden
    assert (result.snoozed_until is not None) is hidden
    assert not result.completed and not result.has_result


async def test_finishing_without_optional_settings_is_permanent_and_idempotent(
    start: StartFixture,
) -> None:
    ctx, member, _, service = start
    member.onboarding_dismissed_at = datetime.now(UTC) - timedelta(days=3)
    result = await service.update(ctx, OnboardingUpdate(completed=True))
    assert result.completed and result.dismissed and not result.has_result
    assert not result.agents and result.goal is None
    assert result.snoozed_until is None and member.onboarding_dismissed_at is None
    timestamp = member.onboarding_completed_at
    assert timestamp is not None
    await service.update(ctx, OnboardingUpdate(completed=True))
    assert member.onboarding_completed_at == timestamp
    result = await service.update(ctx, OnboardingUpdate(dismissed=False))
    assert result.completed and result.dismissed and result.snoozed_until is None


def test_an_update_cannot_reset_completion() -> None:
    with pytest.raises(ValidationError):
        OnboardingUpdate(completed=False)


async def test_joining_another_organization_does_not_inherit_legacy_completion(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, member, _, service = start
    member.joined_at = datetime.now(UTC)
    person = User(
        email="owner@example.com", onboarding_completed_at=member.joined_at - timedelta(days=1)
    )
    monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=person))
    result = await service.state(ctx)
    assert not result.completed and not result.dismissed
    assert not result.has_result


async def test_member_can_open_trusted_setup_chat_without_becoming_ready_to_run(
    start: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = start
    member = AuthContext(
        user_id=ctx.subject_id, organization_id=ctx.organization_id, role=OrgRoleName.MEMBER
    )
    starter = Agent(id=uuid4(), name="AgenticOS", organization_id=ctx.organization_id)
    candidate = AsyncMock(return_value=starter)
    monkeypatch.setattr(ShippedAgentService, "setup_candidate", candidate)
    state = await service.state(member)
    assert state.setup_agent is not None and state.setup_agent.id == starter.id
    assert not state.agents and not state.can_prepare and not state.can_configure_model
    assert not state.has_result
    candidate.assert_awaited_once_with(member, None)


@pytest.mark.parametrize("error", [AuthorizationError, NotFoundError])
async def test_start_never_offers_an_inaccessible_setup_agent(
    start: StartFixture,
    monkeypatch: pytest.MonkeyPatch,
    error: type[AuthorizationError] | type[NotFoundError],
) -> None:
    ctx, _, _, service = start
    monkeypatch.setattr(
        ShippedAgentService, "setup_candidate", AsyncMock(side_effect=error(message="Unavailable"))
    )
    assert (await service.state(ctx)).setup_agent is None
