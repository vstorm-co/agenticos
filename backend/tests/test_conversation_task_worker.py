"""Worker admission, cancellation and crash settlement without paid model calls."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError
from app.worker.jobs import ConversationTaskJob
from app.worker.tasks import conversation_tasks as module

pytestmark = pytest.mark.anyio


def task(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "user_id": uuid4(),
        "source_run_id": uuid4(),
        "source_conversation_id": uuid4(),
        "conversation_id": uuid4(),
        "status": "queued",
        "delivery": "pending",
        "run_id": None,
        "return_run_id": None,
        "agent_id": uuid4(),
        "version_id": uuid4(),
        "source_agent_id": uuid4(),
        "source_version_id": uuid4(),
        "title": "Task",
        "prompt": "Brief",
        "local_target": None,
        "source_model_profile_id": None,
        "outcome": None,
    }
    return SimpleNamespace(**(values | changes))


@asynccontextmanager
async def database():
    db = MagicMock()
    db.commit = AsyncMock()
    yield db


@asynccontextmanager
async def admitted(*_args, **_kwargs):
    yield True


@asynccontextmanager
async def busy(*_args, **_kwargs):
    yield False


async def test_nothing_deleted_replayed_or_unfinished_is_started() -> None:
    rows = [
        None,
        task(status="completed"),
        task(status="completed", delivery="delivered"),
        task(status="queued"),
    ]
    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock()) as get,
    ):
        for row, returning in zip(rows, [False, False, True, True]):
            get.return_value = row
            await module._perform(
                ConversationTaskJob(task_id=uuid4(), organization_id=uuid4()), returning=returning
            )
        assert get.await_count == 4


@pytest.mark.parametrize("status", ["running", "awaiting_approval", "awaiting_answer"])
async def test_a_result_waiting_for_its_source_turn_spends_nothing(status: str) -> None:
    row = task(status="completed")
    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=row)),
        patch.object(
            module.run_repo,
            "get_run",
            new=AsyncMock(return_value=SimpleNamespace(status=status)),
        ),
        patch.object(module, "claim") as claim,
    ):
        await module.return_task(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id)
        )
        claim.assert_not_called()


@pytest.mark.parametrize("returning", [False, True])
async def test_busy_topics_defer_without_replaying_a_model_attempt(returning: bool) -> None:
    row = task(status="completed" if returning else "queued")
    service = MagicMock(queue_return=AsyncMock())
    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=row)),
        patch.object(module.run_repo, "get_run", new=AsyncMock(return_value=None)),
        patch.object(module, "claim", busy),
        patch.object(module, "ConversationTaskService", return_value=service),
        patch(
            "app.services.background_jobs.enqueue", new=AsyncMock(return_value=uuid4())
        ) as enqueue,
        patch.object(module.task_repo, "save", new=AsyncMock()),
    ):
        await module._perform(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id),
            returning=returning,
        )
        assert (service.queue_return.await_count, enqueue.await_count) == (
            (1, 0) if returning else (0, 1)
        )


@pytest.mark.parametrize("returning", [False, True])
async def test_revoked_authority_withdraws_work_before_any_model_call(returning: bool) -> None:
    row = task(status="completed" if returning else "queued")
    service = MagicMock(
        authority=AsyncMock(side_effect=AuthorizationError(message="Revoked")),
        return_context=AsyncMock(side_effect=AuthorizationError(message="Revoked")),
    )
    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=row)),
        patch.object(module.run_repo, "get_run", new=AsyncMock(return_value=None)),
        patch.object(module, "claim", admitted),
        patch.object(module, "ConversationTaskService", return_value=service),
        patch.object(module.task_repo, "save", new=AsyncMock()),
        patch.object(module.AgentRunnerService, "execute", new=AsyncMock()) as execute,
    ):
        await module._perform(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id),
            returning=returning,
        )
        execute.assert_not_called()
        assert row.delivery == "withdrawn"
        assert row.status == ("completed" if returning else "failed")


async def test_crash_settlers_and_reconciler_use_the_durable_record() -> None:
    service = MagicMock(interrupted=AsyncMock(), settle=AsyncMock(), queue_return=AsyncMock())
    row = task(status="completed")
    run = MagicMock()
    payload = ConversationTaskJob(task_id=row.id, organization_id=row.organization_id)
    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module, "ConversationTaskService", return_value=service),
        patch.object(module.task_repo, "unsettled_runs", new=AsyncMock(return_value=[(row, run)])),
        patch.object(module.task_repo, "pending_returns", new=AsyncMock(return_value=[row])),
    ):
        await module.settle_lost_task(payload, "worker died")
        assert service.interrupted.call_args.kwargs["returning"] is False
        await module.settle_lost_return(payload, "worker died")
        assert service.interrupted.call_args.kwargs["returning"] is True
        assert await module.reconcile_tasks() == 2
        service.settle.assert_awaited_once_with(run)
        service.queue_return.assert_awaited_once_with(row)


@pytest.mark.parametrize("in_thread", [False, True])
async def test_live_result_turn_has_agent_attribution_and_no_invented_user_prompt(
    in_thread: bool,
) -> None:
    trace = MagicMock()
    conversation_id, root = uuid4(), uuid4() if in_thread else None
    with (
        patch.object(module.live_turn, "begin", new=AsyncMock(return_value=trace)),
        patch.object(module.live_turn, "publish", new=AsyncMock()) as publish,
        patch.object(module.live_turn, "end", new=AsyncMock()) as end,
        patch.object(module.chat_room, "turn_begun", new=AsyncMock()),
    ):
        async with module._live(
            conversation_id,
            uuid4(),
            uuid4(),
            uuid4(),
            returning=True,
            thread_root_message_id=root,
        ) as frames:
            await frames.emit("model_request_start", {})
            await frames.emit("text_delta", {"content": "Result"})
        assert publish.call_args_list[0].args[1] == "background_task_turn"
        assert publish.call_args_list[0].args[2]["returning"] is True
        assert publish.call_args_list[-1].args[1] == "complete"
        assert all(call.args[1] != "turn_prompt" for call in publish.call_args_list)
        assert all(
            call.args[2]["conversation_id"] == str(conversation_id)
            for call in publish.call_args_list
        )
        assert all(
            call.args[2]["thread_root_message_id"] == (str(root) if root else None)
            for call in publish.call_args_list
        )
        end.assert_awaited_once_with(trace)


@pytest.mark.parametrize("phase", ["busy", "claimed", "claimed-started"])
async def test_deleted_or_concurrently_claimed_tasks_do_not_open_a_second_run(phase: str) -> None:
    row = task()
    second = task(status="running") if phase == "claimed-started" else None
    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock(side_effect=[row, second])),
        patch.object(module, "claim", busy if phase == "busy" else admitted),
        patch.object(module.AgentRunnerService, "execute", new=AsyncMock()) as execute,
    ):
        await module.run_task(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id)
        )
        execute.assert_not_called()


async def test_local_target_is_retained_for_execution() -> None:

    from app.core.permissions import AuthContext
    from app.schemas.local_target import LocalTarget

    local = LocalTarget(
        folder="/approved",
        mode="full_access",
        device_id=uuid4(),
        coding_agent="codex",
        coding_model="fast",
        coding_effort="low",
    )
    row = task(local_target=local.model_dump(mode="json"))
    auth = AuthContext(user_id=row.user_id, organization_id=row.organization_id, role="member")
    service = MagicMock(authority=AsyncMock(return_value=auth))
    seen: list[LocalTarget] = []

    async def execute(*_args, **kwargs):
        seen.append(kwargs["local"])

    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock(return_value=row)),
        patch.object(module.task_repo, "save", new=AsyncMock()),
        patch.object(module, "claim", admitted),
        patch.object(module, "ConversationTaskService", return_value=service),
        patch.object(module.AgentRunnerService, "execute", new=execute),
    ):
        await module.run_task(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id)
        )
    assert seen == [local]


@pytest.mark.parametrize("in_thread", [False, True])
async def test_a_result_keeps_its_source_discussion_and_rechecks_before_models(
    in_thread: bool,
) -> None:
    from app.core.permissions import AuthContext

    row = task(status="completed", outcome="Verified task result")
    root = uuid4() if in_thread else None
    auth = AuthContext(user_id=row.user_id, organization_id=row.organization_id, role="member")
    service = MagicMock(return_context=AsyncMock(return_value=(auth, root)))
    history = [object()]
    histories = MagicMock(model_history=AsyncMock(return_value=history))
    seen = []

    async def execute(_self, _ctx, _agent, _prompt, **options):
        seen.append(options)
        assert options["thread_root_message_id"] == root
        assert options["conversation_id"] == row.source_conversation_id
        assert options["message_history"] is history and options["result_only"] is True
        await options["on_run_open"](SimpleNamespace(id=uuid4()))
        await options["check_model_request"](MagicMock())

    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", AsyncMock(return_value=row)),
        patch.object(module.task_repo, "save", AsyncMock()),
        patch.object(
            module.run_repo, "get_run", AsyncMock(return_value=SimpleNamespace(status="completed"))
        ),
        patch.object(module, "claim", admitted),
        patch.object(module, "ConversationTaskService", return_value=service),
        patch.object(module, "ConversationService", return_value=histories),
        patch.object(module.AgentRunnerService, "execute", execute),
    ):
        await module.return_task(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id)
        )

    assert len(seen) == 1 and service.return_context.await_count == 2
    histories.model_history.assert_awaited_once_with(
        row.source_conversation_id, limit=60, thread_root_message_id=root
    )


@pytest.mark.parametrize("change", ["deleted", "withdrawn", "moved"])
async def test_result_context_changes_stop_before_a_model_request(change: str) -> None:
    from app.core.exceptions import AlreadyExistsError
    from app.core.permissions import AuthContext

    row = task(status="completed", outcome="Result")
    auth = AuthContext(user_id=row.user_id, organization_id=row.organization_id, role="member")
    root = uuid4()
    service = MagicMock(return_context=AsyncMock(side_effect=[(auth, root), (auth, uuid4())]))
    get = AsyncMock(return_value=row)
    model = AsyncMock()

    async def execute(_self, _ctx, _agent, _prompt, **options):
        if change == "deleted":
            get.return_value = None
        elif change == "withdrawn":
            row.delivery = "withdrawn"
        await options["check_model_request"](MagicMock())
        await model()

    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", get),
        patch.object(module.task_repo, "save", AsyncMock()),
        patch.object(module.run_repo, "get_run", AsyncMock(return_value=None)),
        patch.object(module, "claim", admitted),
        patch.object(module, "ConversationTaskService", return_value=service),
        patch.object(
            module,
            "ConversationService",
            return_value=MagicMock(model_history=AsyncMock(return_value=[])),
        ),
        patch.object(module.AgentRunnerService, "execute", execute),
        pytest.raises(AlreadyExistsError),
    ):
        await module.return_task(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id)
        )
    model.assert_not_awaited()


async def test_stop_between_preparation_and_opening_prevents_the_model_call() -> None:
    from app.core.exceptions import AlreadyExistsError
    from app.core.permissions import AuthContext

    row = task()
    stopped = task(status="cancelled")
    auth = AuthContext(user_id=row.user_id, organization_id=row.organization_id, role="member")
    service = MagicMock(authority=AsyncMock(return_value=auth))

    async def execute(*_args, **kwargs):
        await kwargs["on_run_open"](MagicMock(id=uuid4()))
        pytest.fail("A stopped task must not reach its model")

    with (
        patch.object(module, "get_worker_db_context", database),
        patch.object(module.task_repo, "get", new=AsyncMock(side_effect=[row, row, stopped])),
        patch.object(module.task_repo, "save", new=AsyncMock()),
        patch.object(module, "claim", admitted),
        patch.object(module, "ConversationTaskService", return_value=service),
        patch.object(module.AgentRunnerService, "execute", new=execute),
        pytest.raises(AlreadyExistsError),
    ):
        await module.run_task(
            ConversationTaskJob(task_id=row.id, organization_id=row.organization_id)
        )
