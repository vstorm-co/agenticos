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
from app.repositories import agent_repo, organization_assistant_repo
from app.schemas.assistant import AssistantUpdate
from app.services.agent_registry import AgentRegistryService
from app.services.assistant import AssistantService

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """No sandbox on this deployment, unless a test says otherwise - so a test never
    depends on a `sandboxd` that happens to answer on the machine running it."""
    from unittest.mock import AsyncMock

    from app.services.sandbox_connection import SandboxConnectionService

    monkeypatch.setattr(
        SandboxConnectionService, "ensure_local_connection", AsyncMock(return_value=None)
    )


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
    assert waiting.name == "Architect"
    assert waiting.named_by_default
    # It wears its mark from the start, as a picture any agent surface can draw,
    # and the console knows the picture is the mark (drawn in the theme's colours).
    assert waiting.avatar_url is not None
    assert waiting.wears_mark
    assert not waiting.can_configure

    profile = await _model(db, organization)
    ready = await service.state(viewer)

    assert ready.status == "ready"
    assert ready.agent_id == waiting.agent_id
    agent = (await db.execute(select(Agent).where(Agent.id == ready.agent_id))).scalar_one()
    spec = AgentSpec.model_validate(agent.draft_spec)
    assert spec.model_profile_id == profile.id
    assert agent.visibility == "org"
    # The one binding that asks before acting: the Architect drafts agents and
    # invites people, so its template holds those for the person it acts as.
    assert spec.mcp_servers == [PlatformMcpServerRef(account="platform", approval="writes")]
    assert {"ask_user", "web_research", "web_fetch", "skills"} <= {
        binding.id for binding in spec.capabilities
    }
    # Its skills for building agents, installed with it (#2069), and the guide
    # to AgenticOS itself that its questions about the product are answered from.
    assert len(spec.skill_ids) == 8


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
    await AgentRegistryService(db).create(ctx, AgentSpec(name="Architect"))

    state = await AssistantService(db).state(ctx)

    # The handle had to differ; the console still calls it the Architect.
    assert state.name == "Architect (AgenticOS)"
    assert state.named_by_default


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


async def test_an_administrator_sets_its_greeting_and_can_switch_it_off(db: AsyncSession) -> None:
    organization, owner = await _organization(db)
    await _model(db, organization)
    admin = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    member = await _member(db, organization, OrgRoleName.MEMBER)
    service = AssistantService(db)
    installed = await service.state(admin)
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    version_before = agent.current_version_id

    greeted = await service.update(admin, AssistantUpdate(greeting="Cześć!"))
    assert greeted.greeting == "Cześć!"
    # The greeting is the organization's; the agent itself is not republished, so
    # its version history holds only what the Builder put there.
    await db.refresh(agent)
    assert agent.current_version_id == version_before

    off = await service.update(admin, AssistantUpdate(enabled=False))
    assert off.status == "disabled"
    assert off.agent_id is not None
    with pytest.raises(BadRequestError, match="switched off"):
        await AgentRegistryService(db).get_runnable_spec(member, off.agent_id)


async def test_a_switched_off_assistant_is_no_longer_served_over_a2a(db: AsyncSession) -> None:
    """Its card stayed public after it was switched off, with every task refused."""
    organization, owner = await _organization(db)
    await _model(db, organization)
    admin = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    service = AssistantService(db)
    installed = await service.state(admin)
    assert installed.agent_id is not None
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    agent.a2a_enabled = True
    await db.flush()
    assert await agent_repo.get_served_over_a2a(db, agent.id) is not None

    await service.update(admin, AssistantUpdate(enabled=False))

    assert await agent_repo.get_served_over_a2a(db, agent.id) is None
    # And it is what a project's default agent is checked against.
    assert await organization_assistant_repo.switched_off(db, [agent.id, uuid.uuid4()]) == {
        agent.id
    }
    assert await organization_assistant_repo.switched_off(db, []) == set()


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
    # Nothing it set up on the way is left behind: not the gallery skills it
    # installed for the agent, not a half-made assistant row.
    from app.db.models.organization_assistant import OrganizationAssistant
    from app.db.models.skill import Skill

    left = await db.execute(select(Skill).where(Skill.organization_id == organization.id))
    assert left.scalars().all() == []
    assistants = await db.execute(
        select(OrganizationAssistant).where(
            OrganizationAssistant.organization_id == organization.id
        )
    )
    assert assistants.scalars().all() == []


async def test_its_name_and_model_are_the_agents_and_changed_in_the_builder(
    db: AsyncSession,
) -> None:
    """Kacper on #2062: the Architect is an agent like any other, so what the agent
    is - its name, model, knowledge - is edited where every agent's is, and the
    settings only say whether the organization has it and how it greets people."""
    organization, owner = await _organization(db)
    admin = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    service = AssistantService(db)
    installed = await service.state(admin)
    assert installed.agent_id is not None
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()

    # A client still sending the old fields changes nothing with them.
    ignored = await service.update(
        admin, AssistantUpdate.model_validate({"name": "Ola", "model_profile_id": None})
    )
    assert ignored.name == installed.name

    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(update={"name": "Ola z IT"})
    await AgentRegistryService(db).save_draft(admin, agent.id, spec)
    renamed = await service.state(admin)

    # Renamed, it is called what the administrator chose, in every language.
    assert (renamed.name, renamed.named_by_default) == ("Ola z IT", False)


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

    assert published.status == "ready"
    await db.refresh(agent)
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == chosen.id
    assert again == published


async def test_a_picture_of_its_own_replaces_the_mark(db: AsyncSession) -> None:
    from app.services.assistant import AVATAR

    organization, owner = await _organization(db)
    admin = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    service = AssistantService(db)
    installed = await service.state(admin)
    assert installed.agent_id is not None

    await AgentRegistryService(db).set_avatar(
        admin, installed.agent_id, file_data=AVATAR.read_bytes(), content_type="image/png"
    )

    assert not (await service.state(admin)).wears_mark


def test_the_row_names_its_organization_and_agent() -> None:
    from app.db.models.organization_assistant import OrganizationAssistant

    organization_id, agent_id = uuid.uuid4(), uuid.uuid4()
    shown = repr(
        OrganizationAssistant(organization_id=organization_id, agent_id=agent_id, enabled=True)
    )

    assert str(organization_id) in shown and str(agent_id) in shown


async def test_a_deployment_with_a_sandbox_gives_it_files_and_code(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading a pasted agent and running it needs one (#2069, #2070)."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.sandbox_connection import SandboxConnectionService

    monkeypatch.setattr(
        SandboxConnectionService, "ensure_local_connection", AsyncMock(return_value=MagicMock())
    )
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")

    state = await AssistantService(db).state(ctx)

    agent = (await db.execute(select(Agent).where(Agent.id == state.agent_id))).scalar_one()
    sandbox = [
        b for b in AgentSpec.model_validate(agent.draft_spec).capabilities if b.id == "sandbox"
    ]
    assert sandbox and sandbox[0].config == {"include_execute": True}
