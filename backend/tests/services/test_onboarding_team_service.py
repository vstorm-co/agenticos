"""Unit tests for OnboardingTeamService."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, Visibility
from app.db.models.user import User
from app.schemas.agent import AgentCeiling
from app.schemas.onboarding import (
    CreateOnboardingTeamRequest,
    OnboardingProfileRequest,
    ProposedLead,
    ProposedSpecialist,
)
from app.services import onboarding_team
from app.services.onboarding_team import OnboardingTeamService


def test_propose_team_software() -> None:
    svc = OnboardingTeamService(db=MagicMock())
    req = OnboardingProfileRequest(
        role="Engineering Manager",
        industry="software",
        team_size="small",
        goals=["Releases", "API Support"],
    )
    proposal = svc.propose_team(req)
    assert proposal.industry == "software"
    assert "Tech Lead" in proposal.lead.name
    assert len(proposal.specialists) > 0
    assert any(s.key == "software/api-support" for s in proposal.specialists)


def test_propose_team_ecommerce() -> None:
    svc = OnboardingTeamService(db=MagicMock())
    req = OnboardingProfileRequest(
        role="Store Owner",
        industry="ecommerce",
        team_size="solo",
        goals=["Order tracking", "Listing copy"],
    )
    proposal = svc.propose_team(req)
    assert proposal.industry == "ecommerce"
    assert "Store" in proposal.lead.name
    assert len(proposal.specialists) > 0


def test_propose_team_general_fallback() -> None:
    svc = OnboardingTeamService(db=MagicMock())
    req = OnboardingProfileRequest(
        role="Operations",
        industry="unknown_industry_custom",
        team_size="company",
    )
    proposal = svc.propose_team(req)
    assert proposal.industry == "general"
    assert "Chief of Staff" in proposal.lead.name
    assert len(proposal.specialists) >= 2


@dataclass
class BuildHarness:
    service: OnboardingTeamService
    ctx: AuthContext
    user: User
    request: CreateOnboardingTeamRequest
    created: list[Agent]
    ceiling: AsyncMock
    get_user: AsyncMock
    update_user: AsyncMock
    create: AsyncMock
    ensure: AsyncMock
    message: AsyncMock


@pytest.fixture
def build_harness(monkeypatch: pytest.MonkeyPatch) -> BuildHarness:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    user = User(id=ctx.user_id, email="owner@example.test", full_name="Owner")
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    service = OnboardingTeamService(db)
    request = CreateOnboardingTeamRequest(
        lead=ProposedLead(name="Team Lead", role="Lead", description="Coordinates the team"),
        specialists=[
            ProposedSpecialist(
                name="Researcher", role="Research", description="Researches team questions"
            )
        ],
    )
    created: list[Agent] = []

    async def create_agent(_ctx: AuthContext, spec: AgentSpec, *, visibility: Visibility) -> Agent:
        agent = Agent(
            id=uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            name=spec.name,
            slug=onboarding_team.slugify(spec.name),
            description=spec.description,
            draft_spec=spec.model_dump(mode="json"),
            status="draft",
            visibility=visibility,
        )
        created.append(agent)
        return agent

    ceiling = AsyncMock(return_value=AgentCeiling(limit=None, held=None, at_limit=False))
    create = AsyncMock(side_effect=create_agent)
    monkeypatch.setattr(service.registry, "ceiling", ceiling)
    monkeypatch.setattr(service.registry, "create", create)
    monkeypatch.setattr(
        onboarding_team.credential_repo, "list_profiles", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(onboarding_team.agent_repo, "get_by_slug", AsyncMock(return_value=None))
    get_user = AsyncMock(return_value=user)
    update_user = AsyncMock(wraps=onboarding_team.user_repo.update)
    monkeypatch.setattr(onboarding_team.user_repo, "get_by_id", get_user)
    monkeypatch.setattr(onboarding_team.user_repo, "update", update_user)
    ensure = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(onboarding_team.PrimaryConversationService, "ensure", ensure)
    message = AsyncMock()
    monkeypatch.setattr(onboarding_team.conversation_repo, "create_message", message)
    return BuildHarness(
        service,
        ctx,
        user,
        request,
        created,
        ceiling,
        get_user,
        update_user,
        create,
        ensure,
        message,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "ceiling",
    [
        AgentCeiling(limit=None, held=None, at_limit=False),
        AgentCeiling(limit=5, held=3, at_limit=False),
        AgentCeiling(limit=5, held=None, at_limit=False),
    ],
    ids=["unlimited", "exact-headroom", "count-not-visible"],
)
async def test_build_team_uses_the_real_ceiling_and_user_update_contract(
    build_harness: BuildHarness, ceiling: AgentCeiling
) -> None:
    harness = build_harness
    harness.ceiling.return_value = ceiling

    result = await harness.service.build_team(harness.ctx, harness.request)

    assert [agent.name for agent in harness.created] == ["Researcher", "Team Lead"]
    assert [agent.status for agent in result.created_agents] == ["draft", "draft"]
    assert result.lead_agent_id == harness.created[1].id
    harness.ensure.assert_awaited_once_with(
        organization_id=harness.ctx.organization_id,
        user_id=harness.ctx.user_id,
        agent_id=result.lead_agent_id,
        title="Team Lead",
    )
    harness.message.assert_awaited_once()
    harness.update_user.assert_awaited_once()
    update_args = harness.update_user.await_args
    assert update_args is not None
    assert update_args.kwargs["db_user"] is harness.user
    assert harness.user.onboarding_completed_at is not None
    assert result.lead_conversation_id == harness.ensure.return_value


@pytest.mark.anyio
@pytest.mark.parametrize(
    "ceiling",
    [
        AgentCeiling(limit=5, held=4, at_limit=False),
        AgentCeiling(limit=5, held=5, at_limit=True),
        AgentCeiling(limit=5, held=None, at_limit=True),
    ],
    ids=["too-few-slots", "already-full", "full-count-not-visible"],
)
async def test_build_team_refuses_a_known_limit_before_creating_any_agent(
    build_harness: BuildHarness, ceiling: AgentCeiling
) -> None:
    harness = build_harness
    harness.ceiling.return_value = ceiling

    with pytest.raises(BadRequestError, match="organization limit"):
        await harness.service.build_team(harness.ctx, harness.request)

    harness.create.assert_not_awaited()
    harness.ensure.assert_not_awaited()
    harness.update_user.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.security
async def test_build_team_requires_a_signed_in_person_before_writes(
    build_harness: BuildHarness,
) -> None:
    harness = build_harness
    ctx = AuthContext(
        user_id=None,
        api_key_id=uuid4(),
        organization_id=harness.ctx.organization_id,
        role=OrgRoleName.OWNER,
    )

    with pytest.raises(AuthorizationError, match="Sign in"):
        await harness.service.build_team(ctx, harness.request)

    harness.get_user.assert_not_awaited()
    harness.ceiling.assert_not_awaited()
    harness.create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.security
async def test_build_team_refuses_a_missing_user_before_writes(
    build_harness: BuildHarness,
) -> None:
    harness = build_harness
    harness.get_user.return_value = None

    with pytest.raises(NotFoundError, match="User not found"):
        await harness.service.build_team(harness.ctx, harness.request)

    harness.ceiling.assert_not_awaited()
    harness.create.assert_not_awaited()
