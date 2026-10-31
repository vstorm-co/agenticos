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
