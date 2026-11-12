"""Missing and revoked task references must never restart work or complete commitments."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.outcome import Outcome
from app.db.models.task_board import TaskBoard, TaskLink
from app.db.models.virtual_table import VirtualTableRecord
from app.repositories import task as task_repo
from app.schemas.task import TaskFields
from app.services import task_execution as module
from app.services.task_execution import TaskExecution
from app.worker.jobs import WakeTask

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class World:
    service: TaskExecution
    ctx: AuthContext
    board: TaskBoard
    record: VirtualTableRecord
    link: TaskLink
    fields: TaskFields
    trigger: AgentTrigger
    outcome: Outcome


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    board = TaskBoard(
        id=uuid4(),
        organization_id=ctx.organization_id,
        table_id=uuid4(),
        scope_kind="private",
        scope_id=ctx.user_id,
    )
    record = VirtualTableRecord(
        id=uuid4(),
        organization_id=ctx.organization_id,
        table_id=board.table_id,
        revision=1,
        values={},
    )
    link = TaskLink(
        record_id=record.id,
        creator_user_id=ctx.user_id,
        conversation_id=None,
        outcome_id=None,
        trigger_id=None,
        execution_hash=None,
    )
    fields = TaskFields(
        title="Prepare the draft",
        start_at=datetime.now(UTC) - timedelta(minutes=1),
        assignee_user_id=ctx.user_id,
    )
    trigger = AgentTrigger(id=uuid4(), organization_id=ctx.organization_id, is_active=True)
    outcome = Outcome(
        id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id, status="open"
    )
    service = TaskExecution(AsyncMock(spec=AsyncSession))
    for name, value in {
        "record": record,
        "link": link,
        "for_table": board,
        "for_trigger": link,
        "for_outcome": link,
        "board_links": [link],
        "case": None,
        "flush": None,
    }.items():
        monkeypatch.setattr(task_repo, name, AsyncMock(return_value=value))
    monkeypatch.setattr(module, "from_cells", lambda *_: fields)
    monkeypatch.setattr(module, "member_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(module, "enqueue", AsyncMock())
    from app.services import task_access

    monkeypatch.setattr(task_access, "board_allows", AsyncMock(return_value=True))
    for name in ("_stop", "_state", "_project", "_attention"):
        monkeypatch.setattr(service, name, AsyncMock())
    monkeypatch.setattr(service, "_live_table", AsyncMock(return_value=True))
    return World(service, ctx, board, record, link, fields, trigger, outcome)


@pytest.mark.parametrize("operation", ["wake", "unavailable", "finished", "settled", "restored"])
@pytest.mark.parametrize("missing", ["record", "board", "link"])
async def test_missing_task_references_do_not_publish_or_start_work(
    world: World, monkeypatch: pytest.MonkeyPatch, operation: str, missing: str
) -> None:
    if missing == "record":
        monkeypatch.setattr(task_repo, "record", AsyncMock(return_value=None))
    elif missing == "board":
        monkeypatch.setattr(task_repo, "for_table", AsyncMock(return_value=None))
    else:
        for name in ("link", "for_trigger", "for_outcome"):
            monkeypatch.setattr(task_repo, name, AsyncMock(return_value=None))
    if operation == "wake":
        await world.service.wake(
            WakeTask(organization_id=world.ctx.organization_id, task_id=world.record.id, revision=1)
        )
    elif operation == "unavailable":
        await world.service.unavailable(world.trigger)
    elif operation == "finished":
        await world.service.finished(world.trigger, AgentRun(status="completed"))
    elif operation == "settled":
        await world.service.settled(world.outcome)
    else:
        if missing == "link":
            await world.service.restored(world.ctx, world.outcome, task_id=None)
        else:
            with pytest.raises(ConflictError):
                await world.service.restored(world.ctx, world.outcome, task_id=world.record.id)
    world.service._attention.assert_not_awaited()
    world.service._state.assert_not_awaited()


async def test_restoring_a_deleted_task_case_is_an_explicit_conflict(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task_repo, "for_outcome", AsyncMock(return_value=None))
    with pytest.raises(ConflictError, match="deleted or handed off"):
        await world.service.restored(world.ctx, world.outcome, task_id=world.record.id)


@pytest.mark.parametrize("missing_record", [True, False])
async def test_restored_board_does_not_rearm_missing_or_nonplanned_work(
    world: World, monkeypatch: pytest.MonkeyPatch, missing_record: bool
) -> None:
    if missing_record:
        monkeypatch.setattr(task_repo, "record", AsyncMock(return_value=None))
    else:
        world.fields.status = "done"
    queued = AsyncMock()
    monkeypatch.setattr(module, "enqueue", queued)
    await world.service.restored_table(world.board.table_id, world.ctx.organization_id)
    queued.assert_not_awaited()


@pytest.mark.parametrize("available", [True, False])
async def test_departed_reminder_creator_notifies_only_an_authorized_reviewer(
    world: World, monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    monkeypatch.setattr(
        module, "member_context", AsyncMock(side_effect=[None, world.ctx if available else None])
    )
    await world.service.wake(
        WakeTask(organization_id=world.ctx.organization_id, task_id=world.record.id, revision=1)
    )
    world.service._project.assert_awaited_once()
    assert world.service._attention.await_count == int(available)


async def test_absent_table_never_wakes_a_reminder(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(world.service, "_live_table", AsyncMock(return_value=False))
    await world.service.wake(
        WakeTask(organization_id=world.ctx.organization_id, task_id=world.record.id, revision=1)
    )
    world.service._attention.assert_not_awaited()


async def test_finished_agent_work_without_a_human_owner_does_not_create_attention(
    world: World,
) -> None:
    world.link.creator_user_id = None
    await world.service.finished(world.trigger, AgentRun(status="completed"))
    world.service._attention.assert_not_awaited()


async def test_finished_task_does_not_reopen_an_already_terminal_record(world: World) -> None:
    world.fields.status = "done"
    await world.service.finished(world.trigger, AgentRun(status="completed"))
    world.service._attention.assert_not_awaited()


async def test_removed_reviewer_blocks_finished_agent_work_and_notifies_its_creator(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "member_context", AsyncMock(side_effect=[world.ctx, None]))
    await world.service.finished(world.trigger, AgentRun(status="completed"))
    world.service._stop.assert_awaited_once()
    world.service._project.assert_awaited_once()
    assert world.service._attention.await_args.args[3] == world.ctx.user_id


async def test_stale_reviewer_cannot_complete_a_task_after_handoff(world: World) -> None:
    world.outcome.user_id = uuid4()
    await world.service.settled(world.outcome)
    world.service._stop.assert_awaited_once()
    world.service._project.assert_awaited_once()
    assert world.service._attention.await_args.args[3] == world.ctx.user_id


async def test_settling_an_already_terminal_record_does_not_rewrite_it(world: World) -> None:
    world.fields.status = "done"
    await world.service.settled(world.outcome)
    world.service._project.assert_not_awaited()


@pytest.mark.parametrize("status", ["done", "cancelled", "blocked", "waiting_for_user"])
async def test_executing_agent_cannot_publish_its_own_terminal_task_state(
    world: World, status: str
) -> None:
    from dataclasses import replace

    world.link.trigger_id = world.trigger.id
    world.fields.status = status
    with pytest.raises(AuthorizationError, match="cannot close or cancel"):
        await world.service.changed(
            replace(world.ctx, routine_id=world.trigger.id),
            world.board,
            world.record,
            world.link,
            world.fields,
        )


async def test_another_person_cannot_change_live_agent_execution_instructions(world: World) -> None:
    world.link.creator_user_id = uuid4()
    world.link.trigger_id = world.trigger.id
    with pytest.raises(AuthorizationError, match="Stop the current agent execution"):
        await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)


async def test_agent_takeover_requires_stopping_the_current_execution(world: World) -> None:
    world.link.creator_user_id = uuid4()
    world.link.trigger_id = world.trigger.id
    world.fields.next_actor = "agent"
    with pytest.raises(AuthorizationError, match="Stop the current execution"):
        await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)


async def test_unavailable_agent_execution_becomes_blocked(world: World) -> None:
    await world.service.unavailable(world.trigger)
    world.service._stop.assert_awaited_once()
    world.service._project.assert_awaited_once_with(
        world.board, world.record, "blocked", actor=None
    )


@pytest.mark.parametrize("missing", ["link", "record", "board", "none"])
async def test_starting_requires_the_task_link_record_and_board(
    world: World, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    from app.services import task_access

    monkeypatch.setattr(task_access, "execution_allows", AsyncMock(return_value=True))
    target = {"link": "for_trigger", "record": "record", "board": "for_table"}.get(missing)
    if target is not None:
        monkeypatch.setattr(task_repo, target, AsyncMock(return_value=None))
    assert await world.service.started(world.ctx, world.trigger) is (missing == "none")
    assert world.service._state.await_count == int(missing == "none")


async def test_requeueing_an_unchanged_reminder_uses_the_new_record_revision(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repositories import background_job

    cancelled, queued = AsyncMock(), AsyncMock()
    monkeypatch.setattr(background_job, "cancel_queued_for_payload", cancelled)
    monkeypatch.setattr(module, "enqueue", queued)
    await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)
    world.record.revision += 1
    await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)
    assert queued.await_args.args[2].revision == 2
    cancelled.assert_awaited_once()


async def test_agent_work_requires_the_acting_human_to_be_the_owner(world: World) -> None:
    world.fields.next_actor = "agent"
    world.fields.assignee_user_id = uuid4()
    with pytest.raises(AuthorizationError, match="human owner"):
        await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)


async def test_blocked_task_without_a_recipient_does_not_invent_attention(world: World) -> None:
    world.fields.status = "blocked"
    world.fields.assignee_user_id = None
    world.link.creator_user_id = None
    await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)
    world.service._stop.assert_awaited_once()
    world.service._attention.assert_not_awaited()


async def test_handoff_resolves_the_old_case_before_publishing_attention(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.outcome import OutcomeService

    previous = Outcome(id=uuid4(), user_id=uuid4(), status="open")
    world.link.outcome_id = previous.id
    monkeypatch.setattr(task_repo, "case", AsyncMock(return_value=previous))
    resolved = AsyncMock()
    monkeypatch.setattr(OutcomeService, "resolve_task", resolved)
    await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)
    assert world.link.outcome_id is None
    resolved.assert_awaited_once_with(
        previous.id, organization_id=world.ctx.organization_id, project_task=False
    )


async def test_blocked_task_handoff_retires_the_previous_reviewers_case(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.outcome import OutcomeService

    previous = Outcome(id=uuid4(), user_id=uuid4(), status="open")
    world.fields.status = "blocked"
    world.link.outcome_id = previous.id
    monkeypatch.setattr(task_repo, "case", AsyncMock(return_value=previous))
    resolved = AsyncMock()
    monkeypatch.setattr(OutcomeService, "resolve_task", resolved)
    await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)
    assert world.link.outcome_id is None
    resolved.assert_awaited_once_with(previous.id, organization_id=world.ctx.organization_id)
    world.service._attention.assert_awaited_once()


@pytest.mark.parametrize("found", [True, False])
async def test_attention_recovers_a_deduplicated_finding_or_reports_persistence_failure(
    world: World, monkeypatch: pytest.MonkeyPatch, found: bool
) -> None:
    from app.db.models.suggestion import Suggestion
    from app.repositories import suggestion as suggestion_repo
    from app.services.outcome import OutcomeService

    finding = Suggestion(id=uuid4(), payload={}) if found else None
    monkeypatch.setattr(suggestion_repo, "propose", AsyncMock(return_value=None))
    monkeypatch.setattr(suggestion_repo, "for_key", AsyncMock(return_value=finding))
    from app.repositories import outcome as outcome_repo
    from app.services.notifications import NotificationService

    monkeypatch.setattr(OutcomeService, "track_finding", AsyncMock(return_value=world.outcome))
    monkeypatch.setattr(outcome_repo, "set_status", AsyncMock())
    monkeypatch.setattr(outcome_repo, "refresh_context", AsyncMock())
    monkeypatch.setattr(NotificationService, "finding", AsyncMock())
    if not found:
        with pytest.raises(RuntimeError, match="could not be persisted"):
            await TaskExecution._attention(
                world.service,
                world.board,
                world.record,
                world.link,
                world.ctx.subject_id,
                world.fields.title,
            )
    else:
        await TaskExecution._attention(
            world.service,
            world.board,
            world.record,
            world.link,
            world.ctx.subject_id,
            world.fields.title,
        )
        assert finding is not None and finding.status == "open"


async def test_restoring_a_non_task_table_has_no_side_effects(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task_repo, "for_table", AsyncMock(return_value=None))
    await world.service.restored_table(uuid4(), world.ctx.organization_id)
    module.enqueue.assert_not_awaited()


async def test_revoked_execution_is_not_marked_in_progress(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import task_access

    monkeypatch.setattr(task_access, "execution_allows", AsyncMock(return_value=False))
    assert not await world.service.started(world.ctx, world.trigger)
    world.service._state.assert_not_awaited()


async def test_deleting_an_already_detached_record_is_idempotent(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(task_repo, "link", AsyncMock(return_value=None))
    await world.service.deleted(world.ctx, world.record)
    world.service._stop.assert_not_awaited()


async def test_stopping_an_orphaned_trigger_still_withdraws_its_parked_runs(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repositories import background_job
    from app.services.agent_runner import AgentRunnerService

    world.link.trigger_id = world.trigger.id
    cancelled = AsyncMock()
    stopped = AsyncMock()
    monkeypatch.setattr(background_job, "cancel_queued_for_payload", cancelled)
    monkeypatch.setattr(module.agent_trigger_repo, "get_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(task_repo, "parked_runs", AsyncMock(return_value=[]))
    monkeypatch.setattr(AgentRunnerService, "stop_parked_for_workflow", stopped)
    await TaskExecution._stop(world.service, world.link, world.ctx.organization_id)
    assert cancelled.await_count == 2
    stopped.assert_awaited_once()
    assert world.link.trigger_id is None


async def test_settling_after_both_people_leave_keeps_the_task_blocked_without_a_recipient(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "member_context", AsyncMock(return_value=None))
    await world.service.settled(world.outcome)
    world.service._project.assert_awaited_once_with(
        world.board, world.record, "blocked", actor=None
    )
    world.service._attention.assert_not_awaited()


@pytest.mark.parametrize("takeover", [True, False])
async def test_agent_execution_reuses_only_its_owners_working_conversation(
    world: World, monkeypatch: pytest.MonkeyPatch, takeover: bool
) -> None:
    from types import SimpleNamespace

    from app.services.agent_registry import AgentRegistryService
    from app.services.agent_trigger import AgentTriggerService
    from app.services.conversation import ConversationService

    world.fields.next_actor = "agent"
    world.fields.assignee_agent_id = uuid4()
    world.fields.start_at = datetime.now(UTC) + timedelta(hours=1)
    old = uuid4()
    world.link.conversation_id = old
    if takeover:
        world.link.creator_user_id = uuid4()
    monkeypatch.setattr(
        AgentRegistryService, "get_runnable_spec", AsyncMock(return_value=(None, None, uuid4()))
    )
    created = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    monkeypatch.setattr(ConversationService, "create_conversation", created)
    monkeypatch.setattr(AgentTriggerService, "create", AsyncMock(return_value=world.trigger))
    await world.service.changed(world.ctx, world.board, world.record, world.link, world.fields)
    assert world.link.creator_user_id == world.ctx.user_id
    assert created.await_count == int(takeover)
    assert world.link.conversation_id == (created.return_value.id if takeover else old)


async def test_departed_creator_with_no_assignee_blocks_without_inventing_a_recipient(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.fields.assignee_user_id = None
    monkeypatch.setattr(module, "member_context", AsyncMock(return_value=None))
    await world.service.wake(
        WakeTask(organization_id=world.ctx.organization_id, task_id=world.record.id, revision=1)
    )
    world.service._project.assert_awaited_once()
    world.service._attention.assert_not_awaited()
