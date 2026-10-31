"""The AI Architect, installed for every organization on first look (#2063)."""

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
from tests.integration._keys import chatgpt_sign_in, provider_key

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


async def _model(
    db: AsyncSession, organization: Organization, model: str = "gpt-4.1"
) -> ModelProfile:
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=organization.id,
        label=f"Model {uuid.uuid4().hex[:6]}",
        provider="openai",
        model=model,
        secret_id=await provider_key(db, organization.id),
    )
    db.add(profile)
    await db.flush()
    return profile


async def _sign_in(db: AsyncSession, organization: Organization, owner: User) -> ModelProfile:
    """A model on the owner's own ChatGPT sign-in: private, and publishable by them."""
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=organization.id,
        # First in the listing, ahead of any `_model`.
        label="A my ChatGPT",
        provider="openai_codex",
        model="gpt-5.4",
        secret_id=await chatgpt_sign_in(db, organization.id, owner_id=owner.id),
    )
    db.add(profile)
    await db.flush()
    return profile


async def test_its_draft_is_not_held_to_the_only_model_it_was_installed_beside(
    db: AsyncSession,
) -> None:
    """A new agent starts on the organization's only model (#2483), but the
    assistant picks its own: a model in its draft reads as somebody's choice, and
    one that broke before its first publish would keep it waiting for good."""
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    first = await _model(db, organization)
    service = AssistantService(db)
    # Installed switched off: nothing publishes it yet.
    await service.update(ctx, AssistantUpdate(enabled=False))
    first.secret_id = None
    await db.flush()
    second = await _model(db, organization)

    await service.update(ctx, AssistantUpdate(enabled=True))
    ready = await service.state(ctx)

    assert ready.status == "ready"
    agent = await agent_repo.get(db, ready.agent_id, organization_id=organization.id)
    assert agent is not None
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == second.id


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
    # What the chat offers somebody opening it there with nothing said yet (#2301).
    assert spec.starters[0] == "Build me an agent that answers questions from our documents"


async def test_a_speech_model_is_not_one_it_publishes_on(db: AsyncSession) -> None:
    # Publish refuses a text-to-speech model (#2487), so an organization whose only
    # profile is one is still waiting for a model, and the first chat model it
    # adds is the one chosen - not the speech model that came first.
    organization, _owner = await _organization(db)
    viewer = await _member(db, organization, OrgRoleName.VIEWER)
    service = AssistantService(db)
    await _model(db, organization, model="gpt-4o-mini-tts")

    assert (await service.state(viewer)).status == "needs_model"

    chat = await _model(db, organization)
    ready = await service.state(viewer)

    assert ready.status == "ready"
    agent = (await db.execute(select(Agent).where(Agent.id == ready.agent_id))).scalar_one()
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == chat.id


async def test_a_chatgpt_sign_in_is_not_one_it_publishes_on(db: AsyncSession) -> None:
    """One person's subscription: every member's run of the assistant would spend
    it (#2535). Its owner installing the assistant, who could publish on it, does
    not change that; the first model the organization can share is chosen."""
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    await _sign_in(db, organization, owner)

    waiting = await service.state(ctx)

    assert waiting.status == "needs_model"
    agent = (await db.execute(select(Agent).where(Agent.id == waiting.agent_id))).scalar_one()
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id is None

    keyed = await _model(db, organization)
    ready = await service.state(ctx)

    assert ready.status == "ready"
    await db.refresh(agent)
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == keyed.id


@pytest.mark.parametrize("beside_a_shared_model", [False, True])
async def test_a_chatgpt_sign_in_picked_for_it_waits_for_its_author_to_publish(
    db: AsyncSession, beside_a_shared_model: bool
) -> None:
    """The draft keeps the sign-in somebody chose, but the next person to open the
    console does not publish it for them (#2535) - whether or not the organization
    has a model it could share."""
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    installed = await service.state(ctx)
    sign_in = await _sign_in(db, organization, owner)
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"model_profile_id": sign_in.id}
    )
    await AgentRegistryService(db).save_draft(ctx, agent.id, spec)
    if beside_a_shared_model:
        await _model(db, organization)

    state = await service.state(ctx)

    assert state.status == "needs_model"
    await db.refresh(agent)
    assert agent.current_version_id is None
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == sign_in.id


@pytest.mark.security
async def test_a_drafted_model_that_falls_back_to_a_sign_in_waits_for_its_author(
    db: AsyncSession,
) -> None:
    """Somebody's choice stays in the draft, but the next person to open the console
    does not publish a chain that reaches one person's subscription (#2545)."""
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    installed = await service.state(ctx)
    chosen = await _model(db, organization)
    chosen.fallback_profile_ids = [str((await _sign_in(db, organization, owner)).id)]
    await db.flush()
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"model_profile_id": chosen.id}
    )
    await AgentRegistryService(db).save_draft(ctx, agent.id, spec)
    await _model(db, organization)

    state = await service.state(ctx)

    assert state.status == "needs_model"
    await db.refresh(agent)
    assert agent.current_version_id is None
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == chosen.id


@pytest.mark.parametrize("has_valid_model", [False, True])
async def test_architect_skips_a_chat_profile_with_an_incompatible_fallback(
    db: AsyncSession, has_valid_model: bool
) -> None:
    organization, _owner = await _organization(db)
    viewer = await _member(db, organization, OrgRoleName.VIEWER)
    bad = await _model(db, organization)
    bad.label = "A chat with invalid fallback"
    speech = await _model(db, organization, model="gpt-4o-mini-tts")
    bad.fallback_profile_ids = [str(speech.id)]
    valid = await _model(db, organization) if has_valid_model else None
    await db.flush()

    state = await AssistantService(db).state(viewer)

    assert state.status == ("ready" if valid else "needs_model")
    agent = (await db.execute(select(Agent).where(Agent.id == state.agent_id))).scalar_one()
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == (
        valid.id if valid else None
    )


@pytest.mark.security
@pytest.mark.parametrize("onto_a_sign_in", [True, False])
async def test_it_is_not_published_on_a_model_that_falls_back_to_a_chatgpt_sign_in(
    db: AsyncSession, onto_a_sign_in: bool
) -> None:
    """An outage would hand the organization's runs to one person's subscription
    (#2545); a chain with no sign-in in it is published on as before."""
    organization, owner = await _organization(db)
    viewer = await _member(db, organization, OrgRoleName.VIEWER)
    fallback = (
        await _sign_in(db, organization, owner)
        if onto_a_sign_in
        else await _model(db, organization)
    )
    fallback.label = "Z fallback"
    primary = await _model(db, organization)
    primary.label = "A primary"
    primary.fallback_profile_ids = [str(fallback.id)]
    await db.flush()

    state = await AssistantService(db).state(viewer)

    assert state.status == ("needs_model" if onto_a_sign_in else "ready")
    agent = (await db.execute(select(Agent).where(Agent.id == state.agent_id))).scalar_one()
    # Neither the model nor the sign-in it falls back to.
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == (
        None if onto_a_sign_in else primary.id
    )


@pytest.mark.parametrize("compatible", [False, True])
async def test_an_explicit_architect_draft_model_is_preserved(
    db: AsyncSession, compatible: bool
) -> None:
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    installed = await service.state(ctx)
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    chosen = await _model(db, organization, model="gpt-4.1" if compatible else "gpt-4o-mini-tts")
    chosen.label = "Z deliberately selected"
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"model_profile_id": chosen.id}
    )
    await AgentRegistryService(db).save_draft(ctx, agent.id, spec)
    alternative = await _model(db, organization)
    alternative.label = "A otherwise preferred"
    await db.flush()
    state = await service.state(ctx)
    assert state.status == ("ready" if compatible else "needs_model")
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == chosen.id


async def test_a_sign_in_picked_while_it_looked_is_not_published_from_a_stale_read(
    db: AsyncSession,
) -> None:
    """The draft is read again under the lock: a sign-in saved after the caller
    read an empty draft is not published on the shared model it found (#2535)."""
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    installed = await service.update(ctx, AssistantUpdate(enabled=False))
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    stale = Agent(
        id=agent.id,
        organization_id=organization.id,
        name=agent.name,
        slug=agent.slug,
        draft_spec=dict(agent.draft_spec),
    )
    await _model(db, organization)
    sign_in = await _sign_in(db, organization, owner)
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"model_profile_id": sign_in.id}
    )
    await AgentRegistryService(db).save_draft(ctx, agent.id, spec)

    result = await service._publish_when_possible(organization.id, stale)

    assert result.current_version_id is None
    assert AgentSpec.model_validate(result.draft_spec).model_profile_id == sign_in.id


async def test_a_drafted_model_publish_would_refuse_is_kept_unpublished(
    db: AsyncSession,
) -> None:
    """A chat model whose fallback is a speech model is one it could choose, but
    publish refuses the chain, so the author's choice waits rather than being swapped."""
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    installed = await service.state(ctx)
    agent = (await db.execute(select(Agent).where(Agent.id == installed.agent_id))).scalar_one()
    speech = await _model(db, organization, model="gpt-4o-mini-tts")
    chosen = await _model(db, organization)
    chosen.fallback_profile_ids = [str(speech.id)]
    await db.flush()
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"model_profile_id": chosen.id}
    )
    await AgentRegistryService(db).save_draft(ctx, agent.id, spec)

    assert (await service.state(ctx)).status == "needs_model"
    await db.refresh(agent)
    assert AgentSpec.model_validate(agent.draft_spec).model_profile_id == chosen.id


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

    from app.agents.capabilities.sandbox import SandboxConfig
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
    assert sandbox
    config = SandboxConfig.model_validate(sandbox[0].config)
    assert config.backend == "service"
    assert config.include_execute


async def test_refresh_publishes_new_instructions_and_guide_without_changing_configuration(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from app.repositories import skill_repo
    from app.services import agent_templates, skill_library
    from app.services.assistant import GUIDE_KEY, TEMPLATE_KEY
    from app.services.skills import LibraryRefresh

    organization, owner = await _organization(db)
    await _model(db, organization)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    state = await service.state(ctx)
    assert state.agent_id is not None
    agent = await service.registry.get(ctx, state.agent_id)
    before = AgentSpec.model_validate(agent.draft_spec)
    first_id = agent.current_version_id
    assert first_id is not None
    template = agent_templates.get(TEMPLATE_KEY)
    guide = skill_library.gallery_get(GUIDE_KEY)
    assert template is not None and guide is not None
    refreshed = replace(template, instructions=template.instructions + "\nNew shipped instruction.")
    refreshed_guide = replace(guide, content=guide.content + "\nNew shipped guide.")
    monkeypatch.setattr("app.services.assistant._template", lambda: refreshed)
    original_get = skill_library.gallery_get
    monkeypatch.setattr(
        skill_library,
        "gallery_get",
        lambda key: refreshed_guide if key == GUIDE_KEY else original_get(key),
    )
    row = await organization_assistant_repo.get(db, organization.id)
    assert row is not None and row.instructions_fingerprint is not None
    row.enabled = False
    row.greeting = "Our greeting"
    await db.flush()
    dry = await service.refresh(ctx, dry_run=True)
    assert dry.instructions is LibraryRefresh.UPDATE and dry.guide is LibraryRefresh.UPDATE
    assert agent.current_version_id == first_id
    result = await service.refresh(ctx)
    assert result.published_version == 2
    after = AgentSpec.model_validate(agent.draft_spec)
    assert after.instructions == refreshed.instructions
    assert after.model_dump(exclude={"instructions"}) == before.model_dump(exclude={"instructions"})
    old = await agent_repo.get_version(db, first_id, organization_id=organization.id)
    assert old is not None and old.spec["instructions"] == before.instructions
    copy = await skill_repo.get_by_name(db, guide.name, organization_id=organization.id)
    assert copy is not None and copy.content == refreshed_guide.content and copy.version == 2
    assert row.enabled is False and row.greeting == "Our greeting"
    again = await service.refresh(ctx)
    assert again.instructions is LibraryRefresh.CURRENT and again.guide is LibraryRefresh.CURRENT
    assert again.published_version is None and copy.version == 2


@pytest.mark.security
async def test_refresh_protects_organization_edits_and_pending_configuration(
    db: AsyncSession,
) -> None:
    from app.repositories import skill_repo
    from app.schemas.skill import SkillUpdate
    from app.services import skill_library
    from app.services.assistant import GUIDE_KEY
    from app.services.skills import LibraryRefresh, SkillService

    organization, owner = await _organization(db)
    await _model(db, organization)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    state = await service.state(ctx)
    assert state.agent_id is not None
    agent = await service.registry.get(ctx, state.agent_id)
    spec = AgentSpec.model_validate(agent.draft_spec)
    custom = spec.model_copy(update={"instructions": "Our instructions"})
    await service.registry.save_draft(ctx, agent.id, custom)
    await service.registry.publish(ctx, agent.id)
    guide = skill_library.gallery_get(GUIDE_KEY)
    assert guide is not None
    copy = await skill_repo.get_by_name(db, guide.name, organization_id=organization.id)
    assert copy is not None
    await SkillService(db).update(ctx, copy.id, SkillUpdate(content="Our guide"))
    result = await service.refresh(ctx)
    assert result.instructions is LibraryRefresh.EDITED and result.guide is LibraryRefresh.EDITED
    assert agent.draft_spec["instructions"] == "Our instructions" and copy.content == "Our guide"
    await service.registry.save_draft(
        ctx, agent.id, custom.model_copy(update={"description": "Pending description"})
    )
    blocked = await service.refresh(ctx, replace_edited=True)
    assert "pending draft changes" in blocked.detail
    assert agent.draft_spec["description"] == "Pending description" and copy.content == "Our guide"
    await service.registry.save_draft(ctx, agent.id, custom)
    forced = await service.refresh(ctx, replace_edited=True)
    assert forced.published_version == 3
    assert agent.draft_spec["instructions"] == spec.instructions and copy.content == guide.content


@pytest.mark.security
async def test_refresh_refuses_members_and_does_not_install_missing_assistants(
    db: AsyncSession,
) -> None:
    organization, owner = await _organization(db)
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    service = AssistantService(db)
    missing = await service.refresh(ctx)
    assert missing.instructions is None and "not installed" in missing.detail
    assert await organization_assistant_repo.get(db, organization.id) is None
    viewer = await _member(db, organization, OrgRoleName.VIEWER)
    with pytest.raises(AuthorizationError):
        await service.refresh(viewer, replace_edited=True)
