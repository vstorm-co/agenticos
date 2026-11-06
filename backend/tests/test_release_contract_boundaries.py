"""Release boundaries preserve reviewed instructions and orphaned delivery semantics."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, SubagentRef
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("change", ["cycle", "missing", "wrong_agent", "too_many"])
async def test_routine_instruction_review_bounds_delegate_graphs(monkeypatch, change):
    from app.services import routine_actions

    refs = [
        SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())
        for _ in range(65 if change == "too_many" else 1)
    ]
    spec = AgentSpec(name="Root", subagents=refs)

    async def version(_db, identifier, **kwargs):
        ref = next(ref for ref in refs if ref.agent_version_id == identifier)
        if change == "missing":
            return None
        return SimpleNamespace(
            agent_id=uuid4() if change == "wrong_agent" else ref.agent_id,
            spec=AgentSpec(name="Child", subagents=refs if change == "cycle" else []).model_dump(
                mode="json"
            ),
        )

    read = AsyncMock(side_effect=version)
    monkeypatch.setattr(routine_actions.agent_repo, "get_version", read)
    if change == "cycle":
        assert (
            await routine_actions.instruction_fingerprint(
                AsyncMock(), organization_id=uuid4(), spec=spec, project_id=None
            )
            is None
        )
        assert read.await_count == 1
    else:
        with pytest.raises(BadRequestError):
            await routine_actions.instruction_fingerprint(
                AsyncMock(), organization_id=uuid4(), spec=spec, project_id=None
            )


def test_inbox_delivery_changes_the_reviewed_routine_intent():
    from app.db.models.agent_trigger import AgentTrigger
    from app.services.routine_actions import action_intent

    trigger = AgentTrigger(prompt="Check", result_mode="report")
    original = action_intent(trigger)
    trigger.result_mode = "inbox"
    assert action_intent(trigger) != original


async def test_missing_notifications_fail_a_claim_instead_of_attempting_delivery(monkeypatch):
    from app.services import notification_delivery

    now = datetime.now(UTC)
    receipt = MagicMock(id=uuid4(), claimed_at=now, status="pending", channel="email", attempts=1)
    monkeypatch.setattr(
        notification_delivery.notification_repo, "get_delivery", AsyncMock(return_value=receipt)
    )
    monkeypatch.setattr(
        notification_delivery.notification_repo, "get_notification", AsyncMock(return_value=None)
    )
    settle = AsyncMock()
    monkeypatch.setattr(notification_delivery.notification_repo, "settle_delivery", settle)
    assert (
        await notification_delivery.NotificationDeliveryService(AsyncMock()).send_and_settle(
            receipt.id, claimed_at=now
        )
        == "failed"
    )
    assert settle.await_args.kwargs["last_error"] == "notification missing"


async def test_run_retention_drains_device_wait_batches_under_the_same_cutoff(monkeypatch):
    from app.services import retention

    db = MagicMock()
    service = retention.RetentionService(db)
    service._purge_batch = AsyncMock(return_value=0)
    monkeypatch.setattr(retention, "MAX_BATCHES", 2)
    deleted = AsyncMock(side_effect=[retention.BATCH, 0])
    monkeypatch.setattr(retention.retention_repo, "delete_finished_device_waits", deleted)
    result = retention.SweepResult(organization_id=uuid4())
    cutoff = datetime.now(UTC)
    await service._purge("runs", result, cutoff=cutoff)
    assert result.removed["routine_device_waits"] == retention.BATCH
    assert deleted.await_count == 2
    assert deleted.await_args.kwargs["cutoff"] == cutoff


async def test_maintenance_without_an_attribution_agent_never_spends_tokens():
    from app.services.proactive._thinker import ProactiveThinker

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    assert (
        await ProactiveThinker(AsyncMock()).think(
            ctx, feature="maintenance", output_type=str, instructions="Check", prompt="Check"
        )
        is None
    )


@pytest.mark.parametrize("active", [False, True])
async def test_workflow_email_polling_checks_current_active_provider_exposures(monkeypatch, active):
    from app.services import workflow_exposure

    read = AsyncMock(return_value=[MagicMock()] if active else [])
    monkeypatch.setattr(workflow_exposure.workflow_exposure_repo, "list_active", read)
    result = await workflow_exposure.WorkflowExposureService(AsyncMock()).has_polled_email(
        organization_id=uuid4(), source="gmail"
    )
    assert result is active
    assert read.await_args.kwargs["adapter"] == "gmail"
