"""Platform upgrades refresh defaults, not the user's model or unpublished work."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, BudgetSpec, CapabilityBindingSpec, SubagentRef
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.credential import ModelProfile
from app.repositories import agent_repo, skill_repo
from app.schemas.skill import SkillUpdate
from app.services.agent_defaults import STARTER, baseline
from app.services.agent_registry import AgentRegistryService
from app.services.assistant import AssistantService
from app.services.sandbox_connection import SandboxConnectionService
from app.services.shipped_agents import ShippedAgentService
from app.services.skills import SkillService
from tests.integration._keys import provider_key
from tests.integration.test_bootstrap_starters import _agents, _owner

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        SandboxConnectionService, "ensure_local_connection", AsyncMock(return_value=None)
    )


async def test_opening_an_old_organization_installs_both_with_memory(db: AsyncSession) -> None:
    ctx = await _owner(db)
    await AssistantService(db).state(ctx)
    agents = await _agents(db, ctx)
    assert set(agents) == {"AgenticOS", "Architect"}
    for agent in agents.values():
        assert "memory_files" in {
            binding.id for binding in AgentSpec.model_validate(agent.draft_spec).capabilities
        }
        assert agent.shipped_template is not None
    await AssistantService(db).state(ctx)
    assert len(await _agents(db, ctx)) == 2


async def test_upgrade_delivers_new_skills_and_keeps_edits_and_retired_skills(
    db: AsyncSession,
) -> None:
    from app.services import skill_library
    from tests.integration.test_skill_library_refresh import _as_an_earlier_release

    ctx = await _owner(db)
    service = SkillService(db)
    review = await _as_an_earlier_release(db, ctx)
    review_version = review.version
    pages = await service.install_from_library(ctx, "artifact-pages")
    await service.update(ctx, pages.id, SkillUpdate(content="Our own publishing conventions."))
    retired = await service.install_from_library(ctx, "visual-design")
    await service.delete(ctx, retired.id)
    optional = [
        await service.install_from_library(ctx, key)
        for key in ("platform-tables", "platform-context", "platform-skills")
    ]
    old = AgentSpec(
        name="AgenticOS",
        instructions="Earlier shipped instructions",
        capabilities=[CapabilityBindingSpec(id="ask_user"), CapabilityBindingSpec(id="skills")],
        skill_ids=[review.id, pages.id, *(skill.id for skill in optional)],
    )
    agent = await AgentRegistryService(db).create(ctx, old, choose_model=False)
    await agent_repo.update(
        db, agent=agent, update_data={"shipped_template": baseline(STARTER, old)}
    )

    await AssistantService(db).state(ctx)

    required = {
        "platform-agents",
        "platform-workflows",
        "platform-automation",
        "durable-work",
        "document-production",
        "research-and-evidence",
        "presentation-decks",
        "deck-storyline",
        "deck-review",
    }
    for installed in (await _agents(db, ctx)).values():
        spec = AgentSpec.model_validate(installed.draft_spec)
        names = {
            skill.name
            for skill in (
                await skill_repo.get_many(db, spec.skill_ids, organization_id=ctx.organization_id)
            ).values()
        }
        assert required <= names
        assert (
            not {"platform-tables", "platform-context", "platform-skills", "agenticos-guide"}
            & names
        )
        assert "visual-design" not in names
    for retained in optional:
        assert (
            await skill_repo.get(db, retained.id, organization_id=ctx.organization_id) is not None
        )
    refreshed = await skill_repo.get_by_name(db, "code-review", organization_id=ctx.organization_id)
    assert refreshed is not None
    assert refreshed.version == review_version + 1
    assert refreshed.content == skill_library.get("code-review").content
    assert (await skill_repo.get(db, pages.id, organization_id=ctx.organization_id)).content == (
        "Our own publishing conventions."
    )
    assert (
        await skill_repo.get_by_name(db, "visual-design", organization_id=ctx.organization_id)
        is None
    )
    before = refreshed.version
    await AssistantService(db).state(ctx)
    assert refreshed.version == before


@pytest.mark.security
async def test_refresh_keeps_published_model_and_unpublished_budget(db: AsyncSession) -> None:
    ctx = await _owner(db)
    await AssistantService(db).state(ctx)
    registry = AgentRegistryService(db)
    agent = (await _agents(db, ctx))["Architect"]
    profile = ModelProfile(
        id=uuid4(),
        organization_id=ctx.organization_id,
        label="My model",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, ctx.organization_id),
    )
    db.add(profile)
    await db.flush()
    old = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"instructions": "Old shipped prompt", "model_profile_id": profile.id}
    )
    await registry.save_draft(ctx, agent.id, old)
    await registry.publish(ctx, agent.id)
    await agent_repo.update(
        db,
        agent=agent,
        update_data={"shipped_template": baseline("general/platform-assistant", old)},
    )
    pending_model = ModelProfile(
        id=uuid4(),
        organization_id=ctx.organization_id,
        label="Unpublished model choice",
        provider="openai",
        model="gpt-4.1",
        secret_id=profile.secret_id,
    )
    db.add(pending_model)
    await db.flush()
    await registry.save_draft(
        ctx,
        agent.id,
        old.model_copy(
            update={"budget": BudgetSpec(monthly_usd=3), "model_profile_id": pending_model.id}
        ),
    )
    await ShippedAgentService(db).refresh(ctx, agent, "general/platform-assistant")
    version = await agent_repo.get_version(
        db, agent.current_version_id, organization_id=ctx.organization_id
    )
    live = AgentSpec.model_validate(version.spec)
    draft = AgentSpec.model_validate(agent.draft_spec)
    assert live.instructions != "Old shipped prompt"
    assert draft.instructions == live.instructions
    assert live.model_profile_id == profile.id
    assert draft.model_profile_id == pending_model.id
    assert draft.budget.monthly_usd == 3
    assert live.budget == old.budget


async def test_custom_prompt_and_removed_tools_are_preserved(db: AsyncSession) -> None:
    ctx = await _owner(db)
    await AssistantService(db).state(ctx)
    agent = (await _agents(db, ctx))["AgenticOS"]
    registry = AgentRegistryService(db)
    old = AgentSpec.model_validate(agent.draft_spec)
    await agent_repo.update(
        db, agent=agent, update_data={"shipped_template": baseline(STARTER, old)}
    )
    await registry.save_draft(
        ctx,
        agent.id,
        old.model_copy(
            update={
                "instructions": "Only answer invoice questions",
                "skill_ids": [],
                "capabilities": [],
                "mcp_servers": [],
            }
        ),
    )
    refreshed = await ShippedAgentService(db).refresh(ctx, agent, STARTER)
    spec = AgentSpec.model_validate(refreshed.draft_spec)
    assert spec.instructions == "Only answer invoice questions"
    assert spec.capabilities == spec.mcp_servers == spec.skill_ids == []


async def test_a_familiar_name_is_not_proof_an_agent_is_shipped(db: AsyncSession) -> None:
    ctx = await _owner(db)
    registry = AgentRegistryService(db)
    profile = ModelProfile(
        id=uuid4(),
        organization_id=ctx.organization_id,
        label="Ready model",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, ctx.organization_id),
    )
    db.add(profile)
    await db.flush()
    agent = await registry.create(
        ctx,
        AgentSpec(name="AgenticOS", instructions="My own agent", model_profile_id=profile.id),
        choose_model=False,
    )
    await AssistantService(db).state(ctx)
    assert agent.shipped_template is None
    assert AgentSpec.model_validate(agent.draft_spec).instructions == "My own agent"
    assert agent.current_version_id is None


async def test_legacy_defaults_are_adopted_and_receive_new_memory_guidance(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import shipped_agents
    from app.services.agent_defaults import LegacyDefaults, fingerprint

    ctx = await _owner(db)
    registry = AgentRegistryService(db)
    old = AgentSpec(
        name="AgenticOS",
        instructions="Recognized shipped prompt",
        capabilities=[{"id": "clock"}],
        mcp_servers=[{"account": "platform", "approval": "writes"}],
    )
    agent = await registry.create(ctx, old, choose_model=False)
    monkeypatch.setattr(
        shipped_agents,
        "legacy_defaults",
        lambda: {
            STARTER: [
                LegacyDefaults(
                    instructions=fingerprint(old, "instructions"),
                    capabilities=[{"id": "clock"}],
                    mcp_servers=[{"account": "platform", "approval": "writes"}],
                    skills=[],
                    starters=[],
                )
            ]
        },
    )
    updated = await ShippedAgentService(db).starter(ctx)
    spec = AgentSpec.model_validate(updated.draft_spec)
    assert updated.id == agent.id
    assert updated.shipped_template["key"] == STARTER
    from app.services import agent_templates

    assert spec.instructions == agent_templates.get(STARTER).instructions
    assert "memory_files" in {cap.id for cap in spec.capabilities}
    assert updated.current_version_id is None
    # Provenance, rather than a display name, keeps a renamed starter recognizable.
    await agent_repo.update(
        db, agent=updated, update_data={"name": "My assistant", "slug": "my-assistant"}
    )
    assert (await ShippedAgentService(db).starter(ctx)).id == agent.id


async def test_archived_starters_are_not_recreated_or_republished(db: AsyncSession) -> None:
    from app.db.models.agent import AgentStatus

    ctx = await _owner(db)
    await AssistantService(db).state(ctx)
    agent = (await _agents(db, ctx))["AgenticOS"]
    await agent_repo.update(db, agent=agent, update_data={"status": AgentStatus.ARCHIVED.value})
    await AssistantService(db).state(ctx)
    assert len(await _agents(db, ctx)) == 2
    assert agent.status == AgentStatus.ARCHIVED.value
    assert agent.current_version_id is None


async def test_a_draft_prompt_edit_does_not_get_published_by_an_upgrade(db: AsyncSession) -> None:
    ctx = await _owner(db)
    await AssistantService(db).state(ctx)
    registry = AgentRegistryService(db)
    agent = (await _agents(db, ctx))["AgenticOS"]
    old = AgentSpec.model_validate(agent.draft_spec)
    await agent_repo.update(
        db, agent=agent, update_data={"shipped_template": baseline(STARTER, old)}
    )
    await registry.save_draft(
        ctx, agent.id, old.model_copy(update={"instructions": "A new policy, still under review"})
    )
    await ShippedAgentService(db).refresh(ctx, agent, STARTER)
    assert (
        AgentSpec.model_validate(agent.draft_spec).instructions
        == "A new policy, still under review"
    )
    assert agent.current_version_id is None


async def test_a_foreign_agent_is_refused_even_when_its_defaults_are_current(
    db: AsyncSession,
) -> None:
    from app.core.exceptions import NotFoundError

    ctx = await _owner(db)
    other = await _owner(db)
    await AssistantService(db).state(ctx)
    agent = (await _agents(db, ctx))["AgenticOS"]
    with pytest.raises(NotFoundError):
        await ShippedAgentService(db).refresh(other, agent, STARTER)


async def test_published_custom_tool_bindings_stay_typed_during_prompt_refresh(
    db: AsyncSession,
) -> None:
    ctx = await _owner(db)
    await AssistantService(db).state(ctx)
    registry = AgentRegistryService(db)
    agent = (await _agents(db, ctx))["Architect"]
    original = AgentSpec.model_validate(agent.draft_spec)
    old = original.model_copy(update={"instructions": "Old shipped guidance"})
    profile = ModelProfile(
        id=uuid4(),
        organization_id=ctx.organization_id,
        label="My model",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, ctx.organization_id),
    )
    db.add(profile)
    await db.flush()
    custom = AgentSpec.model_validate(
        {
            **old.model_dump(),
            "model_profile_id": profile.id,
            "capabilities": [
                binding.model_dump() for binding in old.capabilities if binding.id != "clock"
            ],
            "mcp_servers": [
                {"account": "platform", "approval": "writes", "allowed_tools": ["list_agents"]}
            ],
        }
    )
    await registry.save_draft(ctx, agent.id, custom)
    await registry.publish(ctx, agent.id)
    await agent_repo.update(
        db,
        agent=agent,
        update_data={"shipped_template": baseline("general/platform-assistant", old)},
    )
    await ShippedAgentService(db).refresh(ctx, agent, "general/platform-assistant")
    version = await agent_repo.get_version(
        db, agent.current_version_id, organization_id=ctx.organization_id
    )
    live = AgentSpec.model_validate(version.spec)
    assert live.instructions == original.instructions
    assert live.capabilities == custom.capabilities
    assert live.mcp_servers == custom.mcp_servers
    assert AgentSpec.model_validate(agent.draft_spec) == live

    delivered = {key: value for key, value in agent.shipped_template.items() if key != "release"}
    current = agent.current_version_id
    await agent_repo.update(db, agent=agent, update_data={"shipped_template": delivered})
    await ShippedAgentService(db).refresh(ctx, agent, "general/platform-assistant")
    assert agent.current_version_id == current


async def _pinned_starter(db: AsyncSession, ctx: AuthContext) -> tuple[Agent, Agent]:
    """A starter as an earlier release left it: the Architect pinned as its delegate."""
    profile = ModelProfile(
        organization_id=ctx.organization_id,
        label="Model",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, ctx.organization_id),
    )
    db.add(profile)
    await db.flush()
    await AssistantService(db).state(ctx)
    agents = await _agents(db, ctx)
    architect, starter = agents["Architect"], agents["AgenticOS"]
    assert architect.current_version_id is not None and starter.current_version_id is not None
    assert AgentSpec.model_validate(starter.draft_spec).subagents == []
    pin = SubagentRef(agent_id=architect.id, agent_version_id=architect.current_version_id)
    shipped = AgentSpec.model_validate(starter.draft_spec).model_copy(update={"subagents": [pin]})
    registry = AgentRegistryService(db)
    await registry.save_draft(ctx, starter.id, shipped)
    await registry.publish(ctx, starter.id)
    await agent_repo.update(
        db,
        agent=starter,
        update_data={"shipped_template": {**baseline(STARTER, shipped), "release": "pinned"}},
    )
    return starter, architect


async def test_starter_drops_the_architect_pin_an_earlier_release_delivered(
    db: AsyncSession,
) -> None:
    """The starter answers platform questions itself; asking the Architect cost a minute."""
    ctx = await _owner(db)
    starter, _architect = await _pinned_starter(db, ctx)

    await AssistantService(db).state(ctx)

    assert AgentSpec.model_validate(starter.draft_spec).subagents == []
    assert starter.current_version_id is not None
    version = await agent_repo.get_version(
        db, starter.current_version_id, organization_id=ctx.organization_id
    )
    assert version is not None and AgentSpec.model_validate(version.spec).subagents == []


async def test_starter_keeps_a_delegate_somebody_chose(db: AsyncSession) -> None:
    ctx = await _owner(db)
    starter, architect = await _pinned_starter(db, ctx)
    registry = AgentRegistryService(db)
    await registry.publish(ctx, architect.id, note="A newer Architect, chosen by hand")
    assert architect.current_version_id is not None
    chosen = SubagentRef(agent_id=architect.id, agent_version_id=architect.current_version_id)
    spec = AgentSpec.model_validate(starter.draft_spec).model_copy(update={"subagents": [chosen]})
    await registry.save_draft(ctx, starter.id, spec)
    await registry.publish(ctx, starter.id)

    await AssistantService(db).state(ctx)

    assert AgentSpec.model_validate(starter.draft_spec).subagents == [chosen]


@pytest.mark.security
async def test_other_agent_catalog_obeys_use_grants_tenant_and_lifecycle(db: AsyncSession) -> None:
    from dataclasses import replace

    from app.db.models.agent import Agent, AgentVersion
    from app.db.models.organization import OrganizationMember
    from app.db.models.resource_grant import ResourceGrant
    from app.db.models.user import User

    owner = await _owner(db)
    foreign = await _owner(db)
    person = User(email=f"catalog-{uuid4()}@example.com", hashed_password="x")
    db.add(person)
    await db.flush()
    db.add(
        OrganizationMember(organization_id=owner.organization_id, user_id=person.id, role="viewer")
    )
    rows: list[Agent] = []
    for name, org, status in [
        ("allowed", owner.organization_id, "published"),
        ("read-only", owner.organization_id, "published"),
        ("hidden", owner.organization_id, "published"),
        ("archived", owner.organization_id, "archived"),
        ("draft", owner.organization_id, "draft"),
        ("foreign", foreign.organization_id, "published"),
    ]:
        row = Agent(
            organization_id=org,
            owner_user_id=owner.user_id,
            name=name,
            slug=name,
            status=status,
            visibility="private",
        )
        db.add(row)
        await db.flush()
        version = AgentVersion(
            agent_id=row.id,
            organization_id=org,
            version=1,
            spec=AgentSpec(name=name).model_dump(mode="json"),
        )
        db.add(version)
        await db.flush()
        row.current_version_id = version.id
        rows.append(row)
        if name != "hidden":
            db.add(
                ResourceGrant(
                    organization_id=org,
                    resource_type="agent",
                    resource_id=row.id,
                    subject_user_id=person.id,
                    level="read" if name == "read-only" else "use",
                )
            )
    await db.flush()
    ctx = replace(owner, user_id=person.id, role="viewer")
    service = AgentRegistryService(db)
    refs = await service.accessible_delegates(ctx, exclude=frozenset())
    assert [ref.agent_id for ref in refs] == [rows[0].id]
    assert await service.accessible_delegates(ctx, exclude=frozenset({rows[0].id})) == []
    assert (
        await service.accessible_delegates(
            replace(ctx, subject_is_publisher_fallback=True), exclude=frozenset()
        )
        == []
    )
    assert await service.accessible_delegates(replace(ctx, user_id=None), exclude=frozenset()) == []


async def test_new_console_agent_gets_common_work_tools_without_agenticos_only_access(
    db: AsyncSession,
) -> None:
    ctx = await _owner(db)
    created = await AgentRegistryService(db).create(
        ctx,
        AgentSpec(name="My assistant"),
        from_starter=True,
        choose_model=False,
    )
    spec = AgentSpec.model_validate(created.draft_spec)
    bindings = {binding.id: binding for binding in spec.capabilities}
    assert {
        "monitor",
        "background_tasks",
        "background_tools",
        "tool_search",
        "conversation_search",
        "subagents",
    } <= bindings.keys()
    assert not (bindings.keys() & {"coding_agent", "computer_use", "browser_use"})
    assert bindings["subagents"].config["allow_dynamic"] is True
    names = {
        skill.name
        for skill in (
            await skill_repo.get_many(db, spec.skill_ids, organization_id=ctx.organization_id)
        ).values()
    }
    assert {
        "platform-agents",
        "platform-automation",
        "durable-work",
        "document-production",
    } <= names
    assert not {"platform-tables", "platform-context", "platform-skills", "agenticos-guide"} & names
    assert "ask_user_question" in spec.instructions
