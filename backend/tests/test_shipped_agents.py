"""Refusals and racing upgrades cannot replace a published platform agent."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent import ShippedAgentChange, ShippedAgentUpdate
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
def installed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        shipped_agents.SandboxConnectionService,
        "can_provide",
        AsyncMock(return_value=bool(agent_templates.settings.SANDBOXD_TOKEN)),
    )
    monkeypatch.setattr(
        shipped_agents.ContextProposalService,
        "bundled_product_context",
        AsyncMock(return_value=None),
    )
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


@pytest.mark.security
@pytest.mark.parametrize("refusal", ["archived", "unmanaged", "cannot_publish"])
async def test_reviewed_updates_require_a_managed_agent_and_publish_authority(
    installed, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    ctx, _, agent, service = installed
    agent.status = "archived" if refusal == "archived" else "published"
    if refusal == "unmanaged":
        agent.shipped_template = None
    service.registry.may_publish = AsyncMock(return_value=refusal != "cannot_publish")
    review = AsyncMock()
    service._review = review
    monkeypatch.setattr(shipped_agents.organization_assistant_repo, "lock_for_install", AsyncMock())
    with pytest.raises(NotFoundError, match="Shipped agent update not found"):
        await service.review_update(ctx, agent.id)
    with pytest.raises(NotFoundError, match="Shipped agent update not found"):
        await service.apply_update(ctx, agent.id, "a" * 64)
    review.assert_not_awaited()


@pytest.mark.parametrize("published", [True, False])
async def test_a_review_reads_the_actual_published_version_and_refuses_its_loss(
    installed, monkeypatch: pytest.MonkeyPatch, published: bool
) -> None:
    ctx, spec, agent, service = installed
    target = AgentSpec(
        name=spec.name,
        instructions="New guidance",
        capabilities=[CapabilityBindingSpec(id="clock")],
    )
    service._target = AsyncMock(return_value=target)
    service.registry.may_publish = AsyncMock(return_value=True)
    monkeypatch.setattr(
        shipped_agents.agent_repo,
        "get_version",
        AsyncMock(return_value=SimpleNamespace(spec=spec.model_dump()) if published else None),
    )
    if published:
        preview = await service.review_update(ctx, agent.id)
        assert {(change.version, change.field) for change in preview.changes} == {
            (side, field)
            for side in ("draft", "published")
            for field in ("instructions", "capabilities")
        }
    else:
        with pytest.raises(NotFoundError, match="published version is missing"):
            await service.review_update(ctx, agent.id)


@pytest.mark.parametrize("changed", [True, False])
async def test_applying_a_review_publishes_only_a_changed_published_version(
    installed, monkeypatch: pytest.MonkeyPatch, changed: bool
) -> None:
    ctx, spec, agent, service = installed
    preview = ShippedAgentUpdate(
        revision="a" * 64,
        changes=[
            ShippedAgentChange(version="published", field="instructions", before="old", after="new")
        ]
        if changed
        else [],
    )
    service.registry.may_publish = AsyncMock(return_value=True)
    service.registry.publish_spec = AsyncMock()
    service.registry.save_draft = AsyncMock()
    service._review = AsyncMock(return_value=(preview, spec, spec, spec))
    update = AsyncMock()
    monkeypatch.setattr(shipped_agents.agent_repo, "update", update)
    monkeypatch.setattr(shipped_agents.organization_assistant_repo, "lock_for_install", AsyncMock())
    await service.apply_update(ctx, agent.id, preview.revision)
    if changed:
        service.registry.publish_spec.assert_awaited_once_with(
            ctx, agent.id, spec, draft=spec, note="Apply reviewed shipped defaults"
        )
        update.assert_awaited_once()
    else:
        service.registry.publish_spec.assert_not_awaited()
        update.assert_not_awaited()
    service.registry.save_draft.assert_not_awaited()


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


async def test_remote_default_sandbox_keeps_shipped_personal_coding_enabled(
    installed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, _, agent, service = installed
    monkeypatch.setattr(agent_templates.settings, "SANDBOXD_TOKEN", "")
    provides = AsyncMock(return_value=True)
    monkeypatch.setattr(shipped_agents.SandboxConnectionService, "can_provide", provides)
    service.ensure_skills = AsyncMock()
    service.registry.template_skills = AsyncMock(return_value=[])
    service.registry.save_draft = AsyncMock()
    monkeypatch.setattr(shipped_agents.agent_repo, "update", AsyncMock(return_value=agent))
    template = agent_templates.get(STARTER)
    assert template is not None
    old = AgentSpec(
        name=template.name,
        instructions="Previous shipped prompt",
        capabilities=list(template.capabilities),
    )
    agent.draft_spec = old.model_dump(mode="json")
    agent.current_version_id = None
    agent.shipped_template = baseline(STARTER, old)
    await service.refresh(ctx, agent, STARTER)
    saved = service.registry.save_draft.call_args.args[2]
    coding = next(binding for binding in saved.capabilities if binding.id == "coding_agent")
    sandbox = next(binding for binding in saved.capabilities if binding.id == "sandbox")
    assert coding.enabled and sandbox.config["backend"] == "service"
    provides.assert_awaited_once_with(ctx.organization_id)


@pytest.mark.parametrize(
    ("release", "prompt_hash"),
    [
        ("nov14", "565f43faa977b55785690d56e3479f030c538a89ec1d0438e1f53c337ac3c0fb"),
        ("nov12", "591db556d4dfe7390b513d139ce0c7e91ed00c80babb7deb9a1f626cdfc1cf37"),
        ("nov12-release", "c32d4cb673c3a5846cdee51bb8f045118b528cdc5e03650c80bd017ae2e07d34"),
    ],
)
@pytest.mark.parametrize("custom_draft_prompt", [False, True])
@pytest.mark.parametrize("original_sandbox", ["service", "state"])
async def test_verified_historical_starter_upgrades_without_overwriting_independent_edits(
    installed,
    monkeypatch: pytest.MonkeyPatch,
    release: str,
    prompt_hash: str,
    custom_draft_prompt: bool,
    original_sandbox: str,
) -> None:
    from pathlib import Path

    from app.agents.spec import BudgetSpec

    ctx, _, agent, service = installed
    historical = agent_templates._read(
        Path(__file__).parent / "fixtures" / "shipped_agents" / release, industry="general"
    )
    row = next(
        row for row in agent_defaults.legacy_defaults()[STARTER] if row.instructions == prompt_hash
    )
    assert row.capabilities == list(historical.capabilities)
    assert row.mcp_servers == list(historical.mcp_servers)
    assert row.skills == list(historical.skills)
    assert row.starters == list(historical.starters)
    live = AgentSpec(
        name="AgenticOS",
        instructions=historical.instructions,
        capabilities=list(historical.capabilities),
        starters=list(historical.starters),
        mcp_servers=[{"account": "platform", "allowed_tools": ["list_agents"]}],
        model_profile_id=uuid4(),
        budget=BudgetSpec(monthly_usd=17),
    )
    if original_sandbox == "state":
        sandbox = next(binding for binding in live.capabilities if binding.id == "sandbox")
        sandbox.config = {**sandbox.config, "backend": "state"}
        sandbox.config.pop("include_execute", None)
    # Recognition must not depend on the availability when the original release
    # was installed: the organization has since acquired a container workspace.
    monkeypatch.setattr(
        shipped_agents.SandboxConnectionService, "can_provide", AsyncMock(return_value=True)
    )
    assert fingerprint(live, "instructions") == prompt_hash
    pending_model = uuid4()
    draft = live.model_copy(
        update={"model_profile_id": pending_model, "budget": BudgetSpec(monthly_usd=3)}
    )
    if custom_draft_prompt:
        # Recognition may still use the published prompt only when explicitly supplied;
        # this path must never treat an edited draft as a shipped starter.
        draft = draft.model_copy(update={"instructions": "Our unpublished instructions"})
    agent.shipped_template = None
    agent.draft_spec = draft.model_dump(mode="json")
    template = agent_templates.get(STARTER)
    assert template is not None
    target = AgentSpec(
        name=template.name,
        instructions=template.instructions,
        capabilities=list(template.capabilities),
        mcp_servers=list(template.mcp_servers),
        starters=list(template.starters),
    )
    service._target = AsyncMock(return_value=target)
    service.registry.template_skills = AsyncMock(return_value=[])
    published = []

    async def save(_ctx, _id, spec):
        agent.draft_spec = spec.model_dump(mode="json")

    async def publish(*args, **kwargs):
        published.append(AgentSpec.model_validate(agent.draft_spec))

    service.registry.save_draft = AsyncMock(side_effect=save)
    service.registry.publish = AsyncMock(side_effect=publish)
    monkeypatch.setattr(
        shipped_agents.agent_repo,
        "get_version",
        AsyncMock(return_value=SimpleNamespace(spec=live.model_dump(mode="json"))),
    )
    monkeypatch.setattr(shipped_agents.agent_repo, "update", AsyncMock(return_value=agent))
    await service.refresh(ctx, agent, STARTER)
    if custom_draft_prompt:
        assert AgentSpec.model_validate(agent.draft_spec) == draft
        assert not published
        service._target.assert_not_awaited()
        return
    assert len(published) == 1
    refreshed = published[0]
    saved = AgentSpec.model_validate(agent.draft_spec)
    assert refreshed.instructions == saved.instructions == target.instructions
    assert refreshed.capabilities == agent_defaults.shipped_capabilities(live, target)
    assert refreshed.starters == target.starters
    assert refreshed.model_profile_id == live.model_profile_id
    assert refreshed.budget == live.budget
    assert saved.model_profile_id == pending_model
    assert saved.budget == draft.budget
    assert refreshed.mcp_servers == saved.mcp_servers == live.mcp_servers
