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
    service._architect_pin = AsyncMock(return_value=None)
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
    release = agent_defaults.digest({"template": release, "architect": None})
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
    monkeypatch.setattr(
        shipped_agents.SandboxConnectionService,
        "ensure_local_connection",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    template = replace(agent_templates.get(ARCHITECT), skills=("not-a-shipped-skill",))
    target = await service._target(ctx, template)
    sandbox = next(cap for cap in target.capabilities if cap.id == "sandbox")
    assert sandbox.config == {"backend": "service", "include_execute": True}


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
