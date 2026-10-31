"""Refresh decisions preserve drafts, edited copies and inactive assistants."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.services import assistant, skill_library
from app.services.assistant import AssistantService, instructions_fingerprint
from app.services.skills import LibraryRefresh, SkillService

pytestmark = pytest.mark.anyio


@pytest.fixture
def installed(monkeypatch):
    service = AssistantService(MagicMock())
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    template = assistant._template()
    skill_id = uuid4()
    spec = AgentSpec(name="Architect", instructions=template.instructions, skill_ids=[skill_id])
    row = SimpleNamespace(
        agent_id=uuid4(), instructions_fingerprint=instructions_fingerprint(spec.instructions)
    )
    agent = SimpleNamespace(
        id=row.agent_id,
        status="published",
        current_version_id=uuid4(),
        draft_spec=spec.model_dump(mode="json"),
    )
    version = SimpleNamespace(spec=spec.model_dump(mode="json"))
    service.registry = MagicMock(
        get=AsyncMock(return_value=agent),
        template_skills=AsyncMock(return_value=[]),
        save_draft=AsyncMock(),
        publish=AsyncMock(return_value=SimpleNamespace(version=2)),
    )
    monkeypatch.setattr(assistant.organization_assistant_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(assistant.organization_assistant_repo, "lock_for_install", AsyncMock())
    monkeypatch.setattr(assistant.organization_assistant_repo, "update", AsyncMock())
    monkeypatch.setattr(assistant.agent_repo, "get_version", AsyncMock(return_value=version))
    monkeypatch.setattr(
        assistant.skill_repo, "get_by_name", AsyncMock(return_value=SimpleNamespace(id=skill_id))
    )
    monkeypatch.setattr(
        SkillService, "refresh_gallery", AsyncMock(return_value=LibraryRefresh.CURRENT)
    )
    return service, ctx, row, agent, version


async def test_archived_assistant_is_left_alone(installed):
    service, ctx, row, agent, version = installed
    agent.status = "archived"
    result = await service.refresh(ctx)
    assert result.instructions is None and "archived" in result.detail
    service.registry.save_draft.assert_not_awaited()


async def test_untracked_instructions_need_explicit_replacement(installed):
    service, ctx, row, agent, version = installed
    row.instructions_fingerprint = None
    agent.draft_spec["instructions"] = "An unknown old copy"
    version.spec = agent.draft_spec.copy()
    result = await service.refresh(ctx, dry_run=True)
    assert result.instructions is LibraryRefresh.UNTRACKED
    service.registry.save_draft.assert_not_awaited()


async def test_missing_guide_is_reported_without_changing_bindings(installed, monkeypatch):
    service, ctx, row, agent, version = installed
    monkeypatch.setattr(assistant.skill_repo, "get_by_name", AsyncMock(return_value=None))
    result = await service.refresh(ctx)
    assert result.guide is None and "missing or detached" in result.detail
    service.registry.save_draft.assert_not_awaited()


async def test_detached_guide_is_left_alone(installed):
    service, ctx, row, agent, version = installed
    version.spec["skill_ids"] = []
    result = await service.refresh(ctx)
    assert result.guide is None


async def test_never_published_assistant_refreshes_only_instructions_in_draft(installed):
    service, ctx, row, agent, version = installed
    agent.current_version_id = None
    agent.draft_spec["instructions"] = "Old shipped instructions"
    row.instructions_fingerprint = instructions_fingerprint("Old shipped instructions")
    result = await service.refresh(ctx)
    assert result.instructions is LibraryRefresh.UPDATE and result.published_version is None
    assert "in draft" in result.detail
    saved = service.registry.save_draft.call_args.args[2]
    assert saved.model_profile_id is None
    assert saved.instructions == assistant._template().instructions
    service.registry.publish.assert_not_awaited()


async def test_broken_version_reference_is_an_explicit_failure(installed, monkeypatch):
    service, ctx, row, agent, version = installed
    monkeypatch.setattr(assistant.agent_repo, "get_version", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="published version"):
        await service.refresh(ctx)


async def test_missing_shipped_guide_is_an_explicit_failure(installed, monkeypatch):
    service, ctx, row, agent, version = installed
    monkeypatch.setattr(skill_library, "gallery_get", lambda key: None)
    with pytest.raises(NotFoundError, match="guide is missing"):
        await service.refresh(ctx)


async def test_missing_gallery_key_is_an_explicit_failure(monkeypatch):
    monkeypatch.setattr(skill_library, "gallery_get", lambda key: None)
    with pytest.raises(NotFoundError, match="No such gallery skill"):
        await SkillService(MagicMock()).refresh_gallery(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER), "missing"
        )


async def test_refresh_attaches_new_workflow_skills_without_dropping_custom_ones(installed):
    service, ctx, row, agent, version = installed
    added = uuid4()
    old = list(agent.draft_spec["skill_ids"])
    service.registry.template_skills.return_value = [SimpleNamespace(id=added)]
    result = await service.refresh(ctx)
    updated = service.registry.save_draft.await_args.args[2]
    assert [str(value) for value in updated.skill_ids] == [*old, str(added)]
    assert result.published_version == 2


async def test_workflow_upgrade_preserves_pending_draft_and_published_settings(installed):
    service, ctx, row, agent, version = installed
    draft = AgentSpec.model_validate(agent.draft_spec)
    draft = draft.model_copy(
        update={"instructions": "Custom pending draft", "starters": ["My pending starter"]}
    )
    agent.draft_spec = draft.model_dump(mode="json")
    published = AgentSpec.model_validate(version.spec)
    added = uuid4()
    service.registry.template_skills.return_value = [SimpleNamespace(id=added)]

    async def guide(agent, spec):
        return spec.model_copy(update={"instructions": spec.instructions + "\nWorkflow support"})

    service.registry.with_assistant_guidance = AsyncMock(side_effect=guide)
    result = await service.refresh(ctx, workflow_support_only=True)
    writes = service.registry.save_draft.await_args_list
    assert len(writes) == 2
    assert writes[0].args[2].starters == published.starters
    assert writes[0].args[2].instructions.startswith(published.instructions)
    assert writes[1].args[2].instructions == "Custom pending draft\nWorkflow support"
    assert writes[1].args[2].starters == ["My pending starter"]
    assert added in writes[1].args[2].skill_ids
    assert result.published_version == 2


async def test_workflow_upgrade_dry_run_never_installs_or_writes(installed):
    service, ctx, row, agent, version = installed
    result = await service.refresh(ctx, workflow_support_only=True, dry_run=True)
    service.registry.template_skills.assert_not_awaited()
    service.registry.save_draft.assert_not_awaited()
    assert result.instructions == LibraryRefresh.UPDATE


async def test_workflow_upgrade_of_unpublished_architect_keeps_it_a_draft(installed):
    service, ctx, row, agent, version = installed
    agent.current_version_id = None
    service.registry.template_skills.return_value = [SimpleNamespace(id=uuid4())]
    service.registry.with_assistant_guidance = AsyncMock(side_effect=lambda agent, spec: spec)
    result = await service.refresh(ctx, workflow_support_only=True)
    service.registry.save_draft.assert_awaited_once()
    service.registry.publish.assert_not_awaited()
    assert result.published_version is None


async def test_workflow_upgrade_is_current_when_no_support_change_is_needed(installed):
    service, ctx, row, agent, version = installed
    service.registry.with_assistant_guidance = AsyncMock(side_effect=lambda agent, spec: spec)
    result = await service.refresh(ctx, workflow_support_only=True)
    service.registry.save_draft.assert_not_awaited()
    service.registry.publish.assert_not_awaited()
    assert result.instructions == LibraryRefresh.CURRENT
