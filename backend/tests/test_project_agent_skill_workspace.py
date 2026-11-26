"""Bound scripts stay with their agent, rather than leaking into shared projects."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai_backends import StateBackend

from app.agents.audience import RunAudience
from app.agents.spec import AgentSpec
from app.services.agent_runner import (
    AgentRunnerService,
    _start_agent_skills_on_first_use,
    _start_turn_on_first_use,
    _with_earlier_attachments_briefing,
)
from app.services.run_project_workspace import RunProjectWorkspace
from app.services.skill_workspace import SKILLS_ROOT
from tests.test_agent_runner import _ctx, _db, _prepared, _sandbox, _skill
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("recorded", [True, False])
async def test_agent_skill_materialisation_is_local_to_its_actual_executor(recorded: bool) -> None:
    prepared = _prepared()
    project_document, agent_document = StateBackend(), StateBackend()
    prepared.workspace = _sandbox(project_document)
    agent = _sandbox(agent_document)
    if not recorded:
        agent.workspace = document_workspace(agent_document)
    skill = _skill()
    await _start_agent_skills_on_first_use(agent, prepared, [skill], {})
    if recorded:
        assert agent_document.files == {}
        assert prepared.materialised_skills is None
    await agent.workspace.exists("first-use")
    path = f"{SKILLS_ROOT}/reconcile/reconcile.py"
    assert agent_document.read_bytes(path) == b"print('ok')"
    assert project_document.files == {}
    assert prepared.materialised_skills is not None
    assert path in prepared.materialised_skills.written


async def test_project_first_use_never_overwrites_agent_skill_proposal_baseline() -> None:
    prepared = _prepared()
    project_document = StateBackend()
    prepared.workspace = _sandbox(project_document)
    baseline = MagicMock()
    prepared.materialised_skills = baseline
    _start_turn_on_first_use(
        prepared.workspace.workspace, prepared, [_skill()], {}, include_skills=False
    )
    await prepared.workspace.workspace.exists("first-use")
    assert prepared.materialised_skills is baseline
    assert project_document.files == {}
    assert prepared.workspace_at_start is not None


async def test_skill_edits_are_proposed_from_agent_not_shared_project() -> None:
    service = AgentRunnerService(_db())
    prepared = _prepared()
    prepared.ctx = _ctx()
    project_document, agent_document = StateBackend(), StateBackend()
    prepared.workspace = _sandbox(project_document)
    agent = _sandbox(agent_document)
    selector = RunProjectWorkspace(
        prepared.workspace.workspace,
        prepared.ctx,
        audience=RunAudience(user_id=prepared.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
    selector.agent_workspace = agent
    prepared.project_workspace = selector
    await _start_agent_skills_on_first_use(agent, prepared, [_skill()], {})
    path = f"{SKILLS_ROOT}/reconcile/reconcile.py"
    await agent.workspace.write_text(path, "print('review this change')")
    service.proposals.record = AsyncMock()
    await service._propose_skill_changes(prepared)
    service.proposals.record.assert_awaited_once()
    changes = service.proposals.record.await_args.args[1]
    assert len(changes) == 1
    assert changes[0].resources["reconcile.py"] == "print('review this change')"
    assert project_document.files == {}


def test_earlier_project_uploads_are_not_described_as_agent_local_files() -> None:
    result = _with_earlier_attachments_briefing(AgentSpec(name="Worker"), project_files=True)
    assert "explicit project file tools" in result.instructions
    assert "not copied into the agent's command workspace" in result.instructions


async def test_service_project_first_use_does_not_close_its_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import agent_runner as module

    opened = _sandbox(StateBackend())
    factory = MagicMock()
    monkeypatch.setattr(module, "SandboxWorkspaceService", factory)
    assert await module._initialize_project_staging(opened, _db()) is None
    factory.assert_not_called()


async def test_stored_project_initialization_failure_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.workspaces import WorkspaceUnavailableError

    from app.core.exceptions import ConcurrentChangeError
    from app.services import agent_runner as module
    from app.services.sandbox_workspace import WorkspaceFlushFailure

    opened = _sandbox(StateBackend())
    opened.kind = "state"
    factory = MagicMock()
    monkeypatch.setattr(module, "SandboxWorkspaceService", factory)
    with pytest.raises(WorkspaceUnavailableError, match="document is unavailable"):
        await module._initialize_project_staging(opened, _db())
    factory.assert_not_called()
    opened.document = MagicMock()
    close = AsyncMock(
        return_value=WorkspaceFlushFailure(
            ConcurrentChangeError(message="Upload conflict", details={})
        )
    )
    factory.return_value.close = close
    with pytest.raises(WorkspaceUnavailableError, match="Upload conflict"):
        await module._initialize_project_staging(opened, _db())
    close.assert_awaited_once_with(opened, keep_spills=True)
