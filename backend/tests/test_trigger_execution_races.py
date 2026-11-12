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
    "change",
    [
        "source_before",
        "source_during",
        "source_during_deleted",
        "preparation_deleted",
        "activation",
        "local_consent",
        "task_removed",
    ],
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
    monkeypatch.setattr(
        module.agent_run_repo, "latest_run_for_conversation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        module.agent_trigger_repo,
        "get_by_id",
        AsyncMock(
            return_value=None
            if change in {"source_during_deleted", "preparation_deleted"}
            else trigger
        ),
    )
    notice = AsyncMock()
    monkeypatch.setattr(module.NotificationService, "routine_blocked", notice)
    monkeypatch.setattr(TaskExecution, "started", AsyncMock(return_value=False))
    errors = {
        "source_before": RoutineSourcesRequired(),
        "source_during": RoutineSourcesRequired(),
        "source_during_deleted": RoutineSourcesRequired(),
        "preparation_deleted": RuntimeError("preparation failed"),
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
    if change in {"source_during_deleted", "preparation_deleted"}:
        notice.assert_not_awaited()
        service._record_attempt.assert_not_awaited()
        service.db.rollback.assert_awaited_once()
    elif change.startswith("source"):
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


@pytest.mark.parametrize("change", ["invalid_active", "invalid_paused", "tenant", "legacy_local"])
async def test_queue_admission_refuses_stale_policies_and_foreign_tenants(monkeypatch, change):
    from datetime import UTC, datetime

    from app.core.exceptions import AuthorizationError

    trigger = _trigger(is_active=change != "invalid_paused")
    if change.startswith("invalid"):
        trigger.approved_sources = {}
    if change == "legacy_local":
        trigger.local_target = {"legacy": True}
    service = _service()
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", enqueue)
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    cleared = AsyncMock()
    monkeypatch.setattr(module.agent_trigger_repo, "clear_fire_marker", cleared)
    monkeypatch.setattr(module.NotificationService, "routine_blocked", AsyncMock())
    if change == "tenant":
        with pytest.raises(AuthorizationError):
            await service.queue_fire(trigger.id, organization_id=uuid4())
    else:
        result = await service.queue_fire(
            trigger.id, organization_id=trigger.organization_id, claimed_at=datetime.now(UTC)
        )
        if change.startswith("invalid"):
            assert result is None
            cleared.assert_awaited_once()
        else:
            assert result == enqueue.return_value


@pytest.mark.parametrize("valid", [False, True])
async def test_worker_dispatch_requires_the_original_source_review_ticket(monkeypatch, valid):
    from datetime import UTC, datetime

    from app.services.routine_sources import read_policy
    from app.worker.jobs import FireTrigger

    trigger = _trigger()
    policy_id = read_policy(trigger.approved_sources).id
    if not valid:
        trigger.approved_sources = {}
    service = _service()
    service.fire = AsyncMock()
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    clear, settle = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module.agent_trigger_repo, "clear_fire_marker", clear)
    monkeypatch.setattr(module.device_wait_repo, "settle", settle)
    await service.fire_job(
        FireTrigger(
            trigger_id=trigger.id,
            source_policy_id=policy_id,
            claimed_at=datetime.now(UTC),
            activation_id=uuid4(),
        )
    )
    assert service.fire.await_count == int(valid)
    assert settle.await_count == int(not valid)
    assert clear.await_count == int(not valid)


@pytest.mark.parametrize(
    "action", ["source_options", "set_source_consents", "action_options", "set_action_consents"]
)
async def test_source_and_action_review_use_the_owned_routine_boundary(monkeypatch, action):
    from app.schemas.routine_actions import RoutineActions
    from app.schemas.routine_sources import RoutineSourceConsent

    service, trigger, ctx = _service(), _trigger(), _ctx()
    service._owned = AsyncMock(return_value=trigger)
    options, replace = AsyncMock(return_value="options"), AsyncMock(return_value="updated")
    if action.startswith("source") or action == "set_source_consents":
        service.sources.options, service.sources.replace = options, replace
    else:
        monkeypatch.setattr(module.RoutineActionService, "options", options)
        monkeypatch.setattr(module.RoutineActionService, "replace", replace)
    args = [ctx, trigger.agent_id, trigger.id]
    if action == "set_source_consents":
        args.append(RoutineSourceConsent(review_token="a" * 64))
    elif action == "set_action_consents":
        args.append(RoutineActions())
    assert await getattr(service, action)(*args) == (
        "updated" if action.startswith("set_") else "options"
    )
    service._owned.assert_awaited_once_with(ctx, trigger.agent_id, trigger.id)


async def test_a_polled_source_loses_admission_when_its_creator_leaves(monkeypatch):
    service = _service()
    service._creator_context = AsyncMock(return_value=None)
    # _service substitutes this boundary for tests of other scheduling behavior.
    assert await module.AgentTriggerService._polled_source_current(service, _trigger()) is False


async def test_a_deleted_native_activation_does_not_create_a_new_blocked_case(monkeypatch):
    service = _service()
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=None))
    notice = AsyncMock()
    monkeypatch.setattr(module.NotificationService, "routine_blocked", notice)
    await service._block_local_activation(
        uuid4(), activation_id=uuid4(), intent="old", name="Routine"
    )
    notice.assert_not_awaited()


@pytest.mark.parametrize("change", ["project_without_owner", "local_on_create", "event_once"])
async def test_creation_refuses_unreviewed_project_or_device_authority(monkeypatch, change):
    from datetime import UTC, datetime

    from app.core.exceptions import BadRequestError
    from app.schemas.local_target import LocalTarget
    from tests.test_agent_triggers import _interval

    service = _service()
    service._version_target = AsyncMock()
    service._delivery_target = AsyncMock()
    data = _interval()
    if change == "project_without_owner":
        data = data.model_copy(update={"project_id": uuid4(), "runs_as_creator": False})
    elif change == "local_on_create":
        data = data.model_copy(
            update={"local_target": LocalTarget(folder="/approved"), "runs_as_creator": True}
        )
    else:
        data = data.model_copy(update={"trigger_type": "event"})
    with pytest.raises(BadRequestError):
        await service.create(
            _ctx(), uuid4(), data, run_once_at=datetime.now(UTC) if change == "event_once" else None
        )


async def test_deleting_a_routine_removed_after_ownership_read_is_an_explicit_missing_resource(
    monkeypatch,
):
    from app.core.exceptions import NotFoundError

    service, trigger = _service(), _trigger()
    service._owned = AsyncMock(return_value=trigger)
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError, match="Trigger not found"):
        await service.delete(_ctx(), trigger.agent_id, trigger.id)


async def test_run_now_refuses_a_stale_polled_source_before_enqueue():
    service, trigger = _service(), _trigger()
    service._owned = AsyncMock(return_value=trigger)
    service._polled_source_current.return_value = False
    service.queue_fire = AsyncMock()
    with pytest.raises(RoutineSourcesRequired):
        await service.run_now(_ctx(), trigger.agent_id, trigger.id)
    service.queue_fire.assert_not_awaited()


@pytest.mark.parametrize("change", ["unadmitted", "stale"])
async def test_polled_places_skip_unreviewed_or_revoked_sources(monkeypatch, change):
    service, trigger = _service(), _trigger()
    monkeypatch.setattr(
        module.agent_trigger_repo, "list_active_for_event_source", AsyncMock(return_value=[trigger])
    )
    service._polled_source_current.return_value = False
    assert (
        await service.polled_places(
            organization_id=trigger.organization_id,
            event_source="gmail",
            source_admissions={} if change == "unadmitted" else None,
        )
        == {}
    )


@pytest.mark.parametrize("change", ["local_upgrade", "removed_local"])
async def test_a_native_fire_keeps_its_durable_device_admission(monkeypatch, change):
    from types import SimpleNamespace

    from app.schemas.local_target import LocalTarget
    from app.services.agent_runner import AgentRunnerService
    from app.services.routine_actions import activation_intent

    service, trigger = _service(), _trigger()
    service._stop_for_monthly_budget = AsyncMock(return_value=False)
    service._creator_context = AsyncMock(return_value=_ctx())
    service.queue_fire = AsyncMock()
    wait = None
    if change == "local_upgrade":
        trigger.local_target = LocalTarget(
            folder="/approved",
            device_id=uuid4(),
            routine_grant=uuid4(),
            mode="read_only",
            operations={"read": True, "write": False, "execute": False},
        ).model_dump(mode="json")
    else:
        wait = SimpleNamespace(
            trigger_id=trigger.id,
            organization_id=trigger.organization_id,
            user_id=_ctx().user_id,
            status="waiting",
            intent_hash=activation_intent(trigger),
            event_context=None,
        )
    monkeypatch.setattr(module.device_wait_repo, "get", AsyncMock(return_value=wait))
    settled = AsyncMock()
    monkeypatch.setattr(module.device_wait_repo, "settle", settled)
    monkeypatch.setattr(module, "local_scope", lambda *args: None)
    execute = AsyncMock()
    monkeypatch.setattr(AgentRunnerService, "execute", execute)
    await service._fire_loaded(trigger, activation_id=uuid4())
    execute.assert_not_awaited()
    assert service.queue_fire.await_count == int(change == "local_upgrade")
    assert settled.await_count == int(change == "removed_local")


async def test_a_fire_with_legacy_review_is_refused_by_execution_without_inventing_a_policy(
    monkeypatch,
):
    trigger, service = _trigger(approved_sources={"legacy": True}), _service()
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    service._fire_loaded = AsyncMock()
    await service.fire(trigger.id)
    assert service._fire_loaded.await_args.kwargs["source_policy_id"] is None


async def test_a_signed_event_with_stale_sources_never_claims_delivery(monkeypatch):
    from unittest.mock import MagicMock

    from tests.test_agent_triggers import _event_trigger

    service, trigger = _service(), _event_trigger()
    service._polled_source_current = AsyncMock(return_value=False)
    service._claim = AsyncMock()
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    monkeypatch.setattr(module, "unseal", lambda *args, **kwargs: "secret")
    monkeypatch.setattr(module.trigger_events, "verify_signature", MagicMock(return_value=True))
    monkeypatch.setattr(module.trigger_events, "event_matches", MagicMock(return_value=True))
    assert await service.prepare_event_fire("github", trigger.id, body=b"{}", headers={}) is None
    service._claim.assert_not_awaited()


@pytest.mark.parametrize("change", ["result_mode", "archived", "target", "expired_during_access"])
async def test_delivery_rechecks_the_reviewed_mode_agent_and_target_before_posting(
    monkeypatch, change
):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock

    from tests.test_agent_triggers import _agent

    trigger = _trigger(
        answer_to="conversation", delivery_conversation_id=uuid4(), result_mode="report"
    )
    service = _service()
    if change == "result_mode":
        trigger.result_mode = "inbox"
    if change == "target":
        trigger.delivery_conversation_id = None
    service.agents.get = AsyncMock(
        return_value=MagicMock(status="archived" if change == "archived" else "published")
    )
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    monkeypatch.setattr(
        module.member_repo, "get_active", AsyncMock(return_value=MagicMock(role="owner"))
    )
    monkeypatch.setattr(
        module.conversation_repo,
        "get_conversation_by_id",
        AsyncMock(
            return_value=MagicMock(
                is_archived=False,
                organization_id=trigger.organization_id,
                user_id=trigger.created_by_user_id,
            )
        ),
    )

    async def access(*args, **kwargs):
        trigger.ends_at = datetime.now(UTC) - timedelta(seconds=1)

    monkeypatch.setattr(module.ConversationService, "get_conversation", access)
    post = AsyncMock()
    monkeypatch.setattr(module.conversation_repo, "create_message", post)
    delivery = await service._deliver(
        trigger,
        agent=_agent(),
        run=MagicMock(routine_policy={"result_mode": "report"}),
        answer="Done",
    )
    assert delivery.status == "unavailable"
    post.assert_not_awaited()


async def test_polled_event_cannot_reuse_a_source_admission_from_an_older_review(monkeypatch):
    from app.services.portals import PolledEvent

    service, trigger = _service(), _trigger()
    monkeypatch.setattr(
        module.agent_trigger_repo, "list_active_for_event_source", AsyncMock(return_value=[trigger])
    )
    assert (
        await service.prepare_polled_fires(
            organization_id=trigger.organization_id,
            event_source="gmail",
            events=[PolledEvent(delivery_id="mail-1", payload={})],
            source_admissions={trigger.id: uuid4()},
        )
        == []
    )


@pytest.mark.parametrize(
    "change", ["foreign", "settled", "already_parked", "deduped_job", "removed_wait"]
)
async def test_native_activation_retries_preserve_the_owned_wait_identity(monkeypatch, change):
    from types import SimpleNamespace

    from app.core.exceptions import AuthorizationError
    from app.schemas.local_target import LocalTarget

    service = _service()
    target = LocalTarget(
        folder="/approved",
        device_id=uuid4(),
        routine_grant=uuid4(),
        mode="read_only",
        operations={"read": True, "write": False, "execute": False},
    )
    trigger = _trigger(local_target=target.model_dump(mode="json"), runs_as_creator=True)
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    existing = SimpleNamespace(
        trigger_id=uuid4() if change == "foreign" else trigger.id,
        organization_id=trigger.organization_id,
        status="cancelled" if change == "settled" else "waiting",
    )
    monkeypatch.setattr(
        module.device_wait_repo,
        "get",
        AsyncMock(
            side_effect=[None, None]
            if change == "removed_wait"
            else [None]
            if change == "already_parked"
            else [existing]
        ),
    )
    monkeypatch.setattr(
        module.device_wait_repo, "park", AsyncMock(return_value=change != "already_parked")
    )
    job = uuid4()
    queue = AsyncMock(return_value=None if change == "deduped_job" else job)
    monkeypatch.setattr(module, "enqueue", queue)
    if change == "foreign":
        with pytest.raises(AuthorizationError):
            await service.queue_fire(trigger.id, organization_id=trigger.organization_id)
    else:
        result = await service.queue_fire(trigger.id, organization_id=trigger.organization_id)
        assert result == (job if change == "removed_wait" else None)
    assert queue.await_count == int(change in {"deduped_job", "removed_wait"})


@pytest.mark.parametrize("change", ["removed", "settled"])
async def test_resumed_delivery_refuses_removed_or_previously_unavailable_receipts(
    monkeypatch, change
):
    from types import SimpleNamespace

    receipt = SimpleNamespace(trigger_id=uuid4(), status="unavailable")
    monkeypatch.setattr(
        module.routine_delivery_repo,
        "get",
        AsyncMock(side_effect=[receipt, None if change == "removed" else receipt]),
    )
    monkeypatch.setattr(module.agent_trigger_repo, "get", AsyncMock(return_value=None))
    service = _service()
    service._deliver = AsyncMock()
    await service.deliver_resumed_answer(uuid4(), uuid4())
    service._deliver.assert_not_awaited()


@pytest.mark.parametrize("removed", [False, True])
async def test_one_shot_finishes_only_after_its_current_trigger_survives_execution(
    monkeypatch, removed
):
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from app.services.agent_runner import AgentRunnerService
    from app.services.task_execution import TaskExecution

    trigger = _trigger(one_shot=True, result_mode="inbox")
    monkeypatch.setattr(module.device_wait_repo, "get", AsyncMock(return_value=None))
    service = _service()
    service._stop_for_monthly_budget = AsyncMock(return_value=False)
    service._creator_context = AsyncMock(return_value=_ctx())
    service._run_log = AsyncMock(return_value=uuid4())
    run = MagicMock(id=uuid4(), status="completed", ended_at=datetime.now(UTC), routine_policy={})
    monkeypatch.setattr(TaskExecution, "started", AsyncMock(return_value=True))
    finished = AsyncMock()
    monkeypatch.setattr(TaskExecution, "finished", finished)
    monkeypatch.setattr(AgentRunnerService, "execute", AsyncMock(return_value=("", run)))
    monkeypatch.setattr(
        module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=None if removed else trigger)
    )
    monkeypatch.setattr(module.OutcomeService, "resolve_routine_failure", AsyncMock())
    await service._fire_loaded(trigger, activation_id=uuid4())
    assert finished.await_count == int(not removed)


async def test_a_legacy_folder_without_a_routine_grant_never_borrows_device_waits(monkeypatch):
    from app.schemas.local_target import LocalTarget

    trigger = _trigger(
        local_target=LocalTarget(folder="/legacy", mode="full_access").model_dump(mode="json")
    )
    service = _service()
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=trigger))
    queue = AsyncMock(return_value=uuid4())
    wait = AsyncMock()
    monkeypatch.setattr(module, "enqueue", queue)
    monkeypatch.setattr(module.device_wait_repo, "get", wait)
    assert await service.queue_fire(trigger.id, organization_id=trigger.organization_id)
    wait.assert_not_awaited()
    assert queue.await_args.kwargs["dedupe_key"] is None


async def test_deleted_routine_leaves_no_attempt_for_a_queued_job(monkeypatch):
    from app.worker.jobs import FireTrigger

    service = _service()
    service.fire = AsyncMock()
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=None))
    result = await service.fire_job(FireTrigger(trigger_id=uuid4()))
    assert result.outcome == "processed" and result.attempt_id is None
    service.fire.assert_not_awaited()
    service._record_attempt.assert_not_awaited()
