"""A queued activation cannot borrow authority changed before model preparation."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import agent_trigger as module
from app.services.routine_devices import RoutineActivationObsolete, RoutineLocalConsentRequired
from app.services.routine_sources import RoutineSourcesRequired
from tests.test_agent_triggers import _ctx, _service, _trigger

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "change", ["source_before", "source_during", "activation", "local_consent", "task_removed"]
)
async def test_late_admission_refusals_never_restart_an_obsolete_activation(monkeypatch, change):
    from app.services.agent_runner import AgentRunnerService
    from app.services.task_execution import TaskExecution

    service, trigger = _service(), _trigger(result_mode="inbox", one_shot=change == "task_removed")
    service._stop_for_monthly_budget = AsyncMock(return_value=False)
    service._creator_context = AsyncMock(return_value=_ctx())
    service._run_log = AsyncMock(return_value=uuid4())
    service._disable = AsyncMock()
    service._block_local_activation = AsyncMock()
    monkeypatch.setattr(module.device_wait_repo, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(module.device_wait_repo, "settle", AsyncMock())
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    notice = AsyncMock()
    monkeypatch.setattr(module.NotificationService, "routine_blocked", notice)
    monkeypatch.setattr(TaskExecution, "started", AsyncMock(return_value=False))
    errors = {
        "source_before": RoutineSourcesRequired(),
        "source_during": RoutineSourcesRequired(),
        "activation": RoutineActivationObsolete(message="Already settled"),
        "local_consent": RoutineLocalConsentRequired(message="Consent changed"),
    }
    execute = AsyncMock(side_effect=errors.get(change))
    monkeypatch.setattr(AgentRunnerService, "execute", execute)
    if change == "source_before":
        service.sources.require_current.side_effect = errors[change]
    activation = uuid4()
    await service._fire_loaded(trigger, activation_id=activation)
    if change in {"source_before", "task_removed"}:
        execute.assert_not_awaited()
    else:
        execute.assert_awaited_once()
        assert "revision" in execute.await_args.args[2]
    if change.startswith("source"):
        notice.assert_awaited_once()
    elif change == "activation":
        service.db.rollback.assert_awaited_once()
        assert module.device_wait_repo.settle.await_args.kwargs["activation_id"] == activation
    elif change == "local_consent":
        service.db.rollback.assert_awaited_once()
        service._block_local_activation.assert_awaited_once()
    else:
        service._disable.assert_awaited_once_with(trigger, reason="task_unavailable")


@pytest.mark.parametrize("change", ["missing", "tenant", "project", "unchanged"])
async def test_project_run_log_cannot_change_its_original_project_binding(monkeypatch, change):
    from types import SimpleNamespace

    trigger = _trigger(project_id=uuid4(), conversation_id=uuid4())
    current = SimpleNamespace(
        organization_id=uuid4() if change == "tenant" else trigger.organization_id,
        project_id=uuid4() if change == "project" else trigger.project_id,
    )
    monkeypatch.setattr(
        module.conversation_repo,
        "get_conversation_by_id",
        AsyncMock(return_value=None if change == "missing" else current),
    )
    service = _service()
    if change == "unchanged":
        assert await service._run_log(trigger, agent_name="Worker") == trigger.conversation_id
    else:
        with pytest.raises(RoutineSourcesRequired):
            await service._run_log(trigger, agent_name="Worker")


async def test_disabling_a_one_shot_task_marks_its_execution_unavailable(monkeypatch):
    from app.services.task_execution import TaskExecution

    service, trigger = _service(), _trigger(one_shot=True)
    stopped = AsyncMock()
    monkeypatch.setattr(TaskExecution, "unavailable", stopped)
    monkeypatch.setattr(module, "record_audit", AsyncMock())
    monkeypatch.setattr(module.device_wait_repo, "cancel_for_trigger", AsyncMock())
    await service._disable(trigger, reason="task_unavailable")
    assert trigger.is_active is False
    stopped.assert_awaited_once_with(trigger)
