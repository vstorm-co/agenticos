"""The AI Architect, installed for every organization on first look (#2063)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, PlatformMcpServerRef
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.assistant import AssistantUpdate
from app.services.agent_registry import AgentRegistryService
from app.services.assistant import AssistantService

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession) -> tuple[Organization, User]:
    owner = await _person(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization, owner


async def _member(db: AsyncSession, organization: Organization, role: str) -> AuthContext:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=organization.id, role=role)


async def _model(db: AsyncSession, organization: Organization) -> ModelProfile:
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=organization.id,
        label=f"Model {uuid.uuid4().hex[:6]}",
        provider="openai",
        model="gpt-4.1",
    )
    db.add(profile)
    await db.flush()
    return profile


async def test_a_viewer_s_first_look_installs_it_and_a_model_publishes_it(
    db: AsyncSession,
) -> None:
    organization, _owner = await _organization(db)
    viewer = await _member(db, organization, OrgRoleName.VIEWER)
    service = AssistantService(db)

    waiting = await service.state(viewer)
    assert waiting.status == "needs_model"
    assert waiting.name == "AI Architect"
    assert not waiting.can_configure

    profile = await _model(db, organization)
    ready = await service.state(viewer)

    assert ready.status == "ready"
    assert ready.agent_id == waiting.agent_id
    assert ready.model_profile_id == profile.id
    agent = (await db.execute(select(Agent).where(Agent.id == ready.agent_id))).scalar_one()
    spec = AgentSpec.model_validate(agent.draft_spec)
    assert agent.visibility == "org"
    assert spec.mcp_servers == [PlatformMcpServerRef(account="platform")]
    assert {"ask_user", "web_research", "web_fetch", "skills"} <= {
        binding.id for binding in spec.capabilities
    }
    # Its skills for building agents, installed with it (#2069).
    assert len(spec.skill_ids) == 7


async def test_one_organization_gets_one_assistant(db: AsyncSession) -> None:
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")

    first = await AssistantService(db).state(ctx)
    again = await AssistantService(db).state(ctx)

    assert first.agent_id == again.agent_id
    assert first.can_configure


async def test_an_agent_already_called_that_does_not_stop_it_existing(db: AsyncSession) -> None:
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    await AgentRegistryService(db).create(ctx, AgentSpec(name="AI Architect"))

    state = await AssistantService(db).state(ctx)

    assert state.name == "AI Architect (AgenticOS)"


@pytest.mark.security
async def test_who_may_talk_to_it_is_agents_run_as_for_any_agent(db: AsyncSession) -> None:
    """Kacper's rule (2026-10-10): no permission, no assistant - a Viewer included."""
    organization, _owner = await _organization(db)
    await _model(db, organization)
    viewer = await _member(db, organization, OrgRoleName.VIEWER)
    member = await _member(db, organization, OrgRoleName.MEMBER)
    registry = AgentRegistryService(db)

    seen_by_viewer = await AssistantService(db).state(viewer)
    seen_by_member = await AssistantService(db).state(member)
    assert seen_by_viewer.agent_id is not None

    assert not seen_by_viewer.can_use
    assert seen_by_member.can_use
    with pytest.raises((AuthorizationError, NotFoundError)):
        await registry.get_runnable_spec(viewer, seen_by_viewer.agent_id)
    agent, _spec, _version = await registry.get_runnable_spec(member, seen_by_viewer.agent_id)
    assert agent.id == seen_by_viewer.agent_id


async def test_an_administrator_configures_it_and_can_switch_it_off(db: AsyncSession) -> None:
    organization, owner = await _organization(db)
    await _model(db, organization)
    second = await _model(db, organization)
    admin = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    member = await _member(db, organization, OrgRoleName.MEMBER)
    service = AssistantService(db)
    await service.state(admin)

    changed = await service.update(
        admin,
        AssistantUpdate(name="Ola z IT", greeting="Cześć!", model_profile_id=second.id),
    )
    assert (changed.name, changed.greeting, changed.model_profile_id) == (
        "Ola z IT",
        "Cześć!",
        second.id,
    )

    off = await service.update(admin, AssistantUpdate(enabled=False))
    assert off.status == "disabled"
    assert off.agent_id is not None
    with pytest.raises(BadRequestError, match="switched off"):
        await AgentRegistryService(db).get_runnable_spec(member, off.agent_id)


async def test_an_organization_at_its_agent_ceiling_hears_it_is_unavailable(
    db: AsyncSession,
) -> None:
    from unittest.mock import AsyncMock, patch

    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    ceiling = BadRequestError(message="This organization has reached its agent limit")

    with patch.object(AgentRegistryService, "create", new=AsyncMock(side_effect=ceiling)):
        state = await AssistantService(db).state(ctx)

    assert (state.status, state.agent_id) == ("unavailable", None)


async def test_settings_that_name_no_model_are_saved_without_publishing(
    db: AsyncSession,
) -> None:
    organization, owner = await _organization(db)
    admin = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    service = AssistantService(db)
    await service.state(admin)

    renamed = await service.update(admin, AssistantUpdate(name="Ola"))

    assert (renamed.name, renamed.status) == ("Ola", "needs_model")


async def test_a_model_chosen_in_the_builder_is_the_one_it_publishes_on(
    db: AsyncSession,
) -> None:
    organization, owner = await _organization(db)
    admin = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    service = AssistantService(db)
    installed = await service.state(admin)
    await _model(db, organization)
    chosen = await _model(db, organization)
    assert installed.agent_id is not None
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"model_profile_id": chosen.id}
    )
    await AgentRegistryService(db).save_draft(admin, agent.id, spec)

    published = await service.state(admin)
    again = await service.state(admin)

    assert (published.status, published.model_profile_id) == ("ready", chosen.id)
    assert again == published


def test_the_row_names_its_organization_and_agent() -> None:
    from app.db.models.organization_assistant import OrganizationAssistant

    organization_id, agent_id = uuid.uuid4(), uuid.uuid4()
    shown = repr(
        OrganizationAssistant(organization_id=organization_id, agent_id=agent_id, enabled=True)
    )

    assert str(organization_id) in shown and str(agent_id) in shown
