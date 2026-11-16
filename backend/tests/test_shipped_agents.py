"""Refusals and racing upgrades cannot replace a published platform agent."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.services import agent_defaults, agent_templates, shipped_agents
from app.services.agent_defaults import (
    ARCHITECT,
    STARTER,
    LegacyDefaults,
    baseline,
    fingerprint,
    template_release,
)
from app.services.shipped_agents import ShippedAgentService

pytestmark = pytest.mark.anyio


@pytest.fixture
def installed():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    spec = AgentSpec(name="AgenticOS", instructions="Old guidance")
    agent = SimpleNamespace(
        id=uuid4(),
        organization_id=ctx.organization_id,
        status="published",
        current_version_id=uuid4(),
        draft_spec=spec.model_dump(mode="json"),
        shipped_template=baseline(STARTER, spec),
    )
    service = ShippedAgentService(MagicMock())
    service.registry.get = AsyncMock(return_value=agent)
    return ctx, spec, agent, service


async def test_a_second_refresher_rechecks_the_locked_agent(installed) -> None:
    ctx, _, agent, service = installed
    template = agent_templates.get(STARTER)
    release = template_release(
        STARTER,
        AgentSpec(
            name=template.name,
            capabilities=agent_templates.for_this_deployment(template.capabilities),
        ).model_dump_json(include={"capabilities"}),
    )
    fresh = SimpleNamespace(
        **{**vars(agent), "shipped_template": {**agent.shipped_template, "release": release}}
    )
    service.registry.get.return_value = fresh
    assert await service.refresh(ctx, agent, STARTER) is fresh


async def test_mismatched_provenance_is_left_alone(installed) -> None:
    ctx, _, agent, service = installed
    agent.shipped_template["key"] = ARCHITECT
    assert await service.refresh(ctx, agent, STARTER) is agent


async def test_missing_published_version_is_an_explicit_failure(
    installed, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, spec, agent, service = installed
    service._target = AsyncMock(return_value=spec)
    monkeypatch.setattr(shipped_agents.agent_repo, "get_version", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="published version is missing"):
        await service.refresh(ctx, agent, STARTER)


async def test_legacy_architect_protects_a_custom_prompt_and_tools(
    installed, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = installed
    old = AgentSpec(
        name="Architect", instructions="Old shipped instructions", capabilities=[{"id": "clock"}]
    )
    history = LegacyDefaults(
        instructions=fingerprint(old, "instructions"),
        capabilities=[{"id": "clock"}],
        mcp_servers=[],
        skills=[],
        starters=[],
    )
    monkeypatch.setattr(shipped_agents, "legacy_defaults", lambda: {ARCHITECT: [history]})
    service.registry.template_skills = AsyncMock(return_value=[])
    custom = AgentSpec(
        name="My Architect",
        instructions="My own policy",
        capabilities=[{"id": "memory_files"}],
        mcp_servers=[{"account": "platform", "allowed_tools": ["list_agents"]}],
    )
    previous = await service._legacy_baseline(ctx, custom, ARCHITECT)
    assert (
        previous["instructions"]
        == previous["capabilities"]
        == previous["mcp_servers"]
        == "customized"
    )


async def test_architect_gets_execution_only_when_a_sandbox_is_available(
    installed, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = installed
    service.registry.template_skills = AsyncMock(return_value=[])
    service.ensure_skills = AsyncMock()
    monkeypatch.setattr(
        shipped_agents.SandboxConnectionService,
        "ensure_local_connection",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    template = replace(agent_templates.get(ARCHITECT), skills=("not-a-shipped-skill",))
    target = await service._target(ctx, template)
    sandbox = next(cap for cap in target.capabilities if cap.id == "sandbox")
    assert sandbox.config == {"backend": "service", "include_execute": True}


async def test_skill_installation_requires_an_actual_organization_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shipped_agents.organization_assistant_repo, "lock_for_install", AsyncMock())
    monkeypatch.setattr(shipped_agents.member_repo, "first_owner_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="no owner"):
        await ShippedAgentService(MagicMock()).ensure_skills(uuid4())


def test_a_library_update_changes_the_release_even_when_the_skill_is_not_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import skill_library

    entries = skill_library.library()
    template_release.cache_clear()
    try:
        before = template_release(STARTER, "deployment")
        monkeypatch.setattr(
            skill_library,
            "library",
            lambda: tuple(
                replace(entry, content=entry.content + "\nUpdated policy.")
                if entry.key == "refund-policy"
                else entry
                for entry in entries
            ),
        )
        template_release.cache_clear()
        assert template_release(STARTER, "deployment") != before
    finally:
        template_release.cache_clear()


async def test_missing_templates_fail_instead_of_adopting_empty_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_templates, "get", lambda key: None)
    with pytest.raises(NotFoundError, match="template is missing"):
        ShippedAgentService._template("missing")
    with pytest.raises(ValueError, match="Missing shipped agent template"):
        agent_defaults.template_release("missing", "deployment")


async def test_an_existing_install_stamp_is_authoritative_without_guessing_by_similarity(
    installed, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, spec, _, service = installed
    monkeypatch.setattr(shipped_agents, "legacy_defaults", lambda: {ARCHITECT: []})
    service.registry.template_skills = AsyncMock(return_value=[])
    stamp = fingerprint(spec, "instructions")
    previous = await service._legacy_baseline(
        ctx, spec, ARCHITECT, legacy_instructions_fingerprint=stamp
    )
    assert previous["instructions"] == stamp
    edited = spec.model_copy(update={"instructions": "Changed by the owner"})
    previous = await service._legacy_baseline(
        ctx, edited, ARCHITECT, legacy_instructions_fingerprint=stamp
    )
    assert previous["instructions"] == "customized"


async def test_refresh_updates_an_already_bound_shipped_skill_before_using_its_template(
    installed, monkeypatch
):
    from app.services.skills import LibraryRefresh

    ctx, _, _, service = installed
    entry = next(
        skill for industry in shipped_agents.skill_library.gallery() for skill in industry.skills
    )
    template = replace(agent_templates.get(STARTER), skills=(entry.key,))
    service.ensure_skills = AsyncMock()
    service.registry.template_skills = AsyncMock(
        return_value=[SimpleNamespace(id=uuid4(), name=entry.name)]
    )
    refresh = AsyncMock(return_value=LibraryRefresh.CURRENT)
    monkeypatch.setattr(shipped_agents.SkillService, "refresh_gallery", refresh)
    target = await service._target(ctx, template)
    assert target.skill_ids
    refresh.assert_awaited_once_with(ctx, entry.key)


async def test_a_legacy_architect_with_a_sandbox_is_recognized_without_duplicating_it(
    installed, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, service = installed
    history = LegacyDefaults(
        instructions="legacy",
        capabilities=[{"id": "sandbox", "config": {"backend": "state"}}],
        mcp_servers=[],
        skills=[],
        starters=[],
    )
    monkeypatch.setattr(shipped_agents, "legacy_defaults", lambda: {ARCHITECT: [history]})
    service.registry.template_skills = AsyncMock(return_value=[])
    spec = AgentSpec(
        name="Architect",
        capabilities=[{"id": "sandbox", "config": {"backend": "service", "include_execute": True}}],
    )
    previous = await service._legacy_baseline(ctx, spec, ARCHITECT)
    assert previous["capabilities"] == fingerprint(spec, "capabilities")
    assert history.capabilities == [{"id": "sandbox", "config": {"backend": "state"}}]


@pytest.mark.parametrize("case", ["missing", "different", "published", "archived", "versioned"])
async def test_setup_reply_never_admits_other_or_already_published_agents(
    installed, monkeypatch, case
):
    ctx, _, agent, service = installed
    candidate = None if case == "missing" else agent
    agent.status = "draft"
    agent.current_version_id = None
    if case == "published":
        agent.status = "published"
    if case == "archived":
        agent.status = "archived"
    if case == "versioned":
        agent.current_version_id = uuid4()
    monkeypatch.setattr(
        shipped_agents.agent_repo, "get_shipped_starter", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        shipped_agents.organization_assistant_repo, "get", AsyncMock(return_value=None)
    )
    assert await service.setup_candidate(ctx, uuid4() if case == "different" else agent.id) is None
    service.registry.get.assert_not_awaited()


async def test_unconfigured_starter_setup_still_checks_the_callers_run_grant(
    installed, monkeypatch
):
    from app.core.permissions import Perm

    ctx, _, agent, service = installed
    agent.status = "draft"
    agent.current_version_id = None
    monkeypatch.setattr(
        shipped_agents.agent_repo, "get_shipped_starter", AsyncMock(return_value=agent)
    )
    assert await service.setup_candidate(ctx, None) is agent
    service.registry.get.assert_awaited_once_with(ctx, agent.id, perm=Perm.AGENTS_RUN)
    service.registry.get.side_effect = NotFoundError(message="Agent not found")
    with pytest.raises(NotFoundError):
        await service.setup_candidate(ctx, agent.id)


@pytest.mark.parametrize(
    "case", ["draft", "disabled", "other", "published", "archived", "versioned", "denied"]
)
async def test_architect_setup_uses_organization_identity_and_run_access(
    installed, monkeypatch, case
):
    ctx, _, agent, service = installed
    agent.status = "draft"
    agent.current_version_id = None
    if case in ("published", "archived"):
        agent.status = case
    if case == "versioned":
        agent.current_version_id = uuid4()
    row = SimpleNamespace(
        enabled=case != "disabled", agent_id=uuid4() if case == "other" else agent.id
    )
    monkeypatch.setattr(
        shipped_agents.agent_repo, "get_shipped_starter", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        shipped_agents.organization_assistant_repo, "get", AsyncMock(return_value=row)
    )
    if case == "denied":
        service.registry.get.side_effect = NotFoundError(message="Agent not found")
        with pytest.raises(NotFoundError):
            await service.setup_candidate(ctx, agent.id)
    else:
        result = await service.setup_candidate(ctx, agent.id)
        assert result is (agent if case == "draft" else None)
    if case in ("disabled", "other"):
        service.registry.get.assert_not_awaited()
    assert await service.setup_candidate(ctx, None) is None
