"""Initial required asset failures release the workspace before a PreparedRun exists."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExternalServiceError
from app.services import agent_runner
from app.services.agent_runner import AgentRunnerService
from app.services.sandbox_workspace import OpenWorkspace
from app.services.skill_workspace import MaterialisedSkills
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


def opened() -> OpenWorkspace:
    return OpenWorkspace(
        workspace=document_workspace(),
        kind="state",
        scope="conversation",
        scope_key="conversation",
        row_id=None,
    )


@pytest.mark.parametrize("cancelled", [False, True])
async def test_initial_materialization_refusal_or_cancellation_closes_once(
    monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    refusal = (
        asyncio.CancelledError()
        if cancelled
        else ExternalServiceError(message="Required binary file is unavailable")
    )
    write = AsyncMock(side_effect=refusal)
    monkeypatch.setattr(agent_runner, "materialise_skills", write)
    service = AgentRunnerService(MagicMock(spec=AsyncSession))
    close = AsyncMock(return_value=None)
    monkeypatch.setattr(service.workspaces, "close", close)
    workspace = opened()
    with pytest.raises(type(refusal)):
        await service._materialise_initial_skills(workspace, [], {})
    close.assert_awaited_once_with(workspace)


async def test_success_keeps_workspace_owned_by_terminal_run_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = MaterialisedSkills()
    monkeypatch.setattr(agent_runner, "materialise_skills", AsyncMock(return_value=state))
    service = AgentRunnerService(MagicMock(spec=AsyncSession))
    close = AsyncMock(return_value=None)
    monkeypatch.setattr(service.workspaces, "close", close)
    assert await service._materialise_initial_skills(opened(), [], {}) is state
    close.assert_not_awaited()


async def test_cleanup_flush_refusal_is_visible_without_masking_asset_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.services.sandbox_workspace import WorkspaceFlushFailure

    original = ExternalServiceError(message="Required asset unavailable")
    monkeypatch.setattr(agent_runner, "materialise_skills", AsyncMock(side_effect=original))
    service = AgentRunnerService(MagicMock(spec=AsyncSession))
    close = AsyncMock(
        return_value=WorkspaceFlushFailure(ExternalServiceError(message="Cleanup flush refused"))
    )
    monkeypatch.setattr(service.workspaces, "close", close)
    with pytest.raises(ExternalServiceError) as caught:
        await service._materialise_initial_skills(opened(), [], {})
    assert caught.value is original
    assert "skill_preparation_cleanup_failed" in caplog.text
    close.assert_awaited_once()
