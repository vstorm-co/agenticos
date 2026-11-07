"""Question readiness, durable dispatch and ownership admission edge cases."""

import dataclasses
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import BadRequestError
from app.db.models.workflow_run import WorkflowRunStatus
from app.services.workflow_execution import context, questions
from tests.test_workflow_agent_node import _dispatch

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("status", "state", "expected"),
    [
        ("running", None, False),
        ("awaiting_answer", None, False),
        ("awaiting_answer", {"question_results": {}}, False),
        ("awaiting_answer", {"question_results": {"q1": "declined"}}, True),
        ("cancelled", None, True),
        ("awaiting_approval", None, True),
    ],
)
def test_only_accepted_or_ended_questions_are_ready(status, state, expected):
    assert questions.ready(SimpleNamespace(status=status, paused_state=state)) is expected


@pytest.mark.parametrize(
    "fields",
    [{"status": "running"}, {"waiting_reason": "approval"}, {"waiting_agent_run_id": None}],
)
async def test_an_answer_cannot_be_attached_to_a_step_not_waiting_on_a_question(fields):
    node = SimpleNamespace(
        id=uuid.uuid4(),
        status="waiting",
        waiting_reason="question",
        waiting_agent_run_id=uuid.uuid4(),
    )
    for name, value in fields.items():
        setattr(node, name, value)
    with pytest.raises(BadRequestError, match="not waiting for an answer"):
        await questions.accept(
            MagicMock(), _dispatch().auth, run=MagicMock(), node=node, responses={}
        )


@pytest.mark.parametrize("outbox_status", [None, "done", "pending", "claimed"])
async def test_a_duplicate_dispatch_only_absorbs_a_conflict_when_a_live_dispatch_exists(
    outbox_status,
):
    db = MagicMock()
    db.begin_nested.return_value.__aenter__ = AsyncMock()
    db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    node = SimpleNamespace(
        id=uuid.uuid4(),
        status="waiting",
        waiting_reason="question",
        waiting_agent_run_id=uuid.uuid4(),
    )
    row = None if outbox_status is None else SimpleNamespace(status=outbox_status)
    with (
        patch("app.services.agent_runner.AgentRunnerService") as runner,
        patch.object(
            questions.dispatch_queue,
            "queue_dispatch",
            AsyncMock(side_effect=IntegrityError("insert", {}, Exception())),
        ),
        patch.object(
            questions.workflow_run_repo,
            "get_outbox_for_node_run_for_update",
            AsyncMock(return_value=row),
        ),
    ):
        runner.return_value.accept_answers = AsyncMock()
        if outbox_status in ("pending", "claimed"):
            await questions.accept(db, _dispatch().auth, run=MagicMock(), node=node, responses={})
        else:
            with pytest.raises(IntegrityError):
                await questions.accept(
                    db, _dispatch().auth, run=MagicMock(), node=node, responses={}
                )


@pytest.mark.parametrize(
    "condition",
    [
        "lost",
        "missing_run",
        "terminal",
        "missing_node",
        "cancelled_node",
        "missing_attempt",
        "later_attempt",
    ],
)
async def test_a_stale_or_cancelled_step_cannot_start_a_new_child(condition):
    current = _dispatch()
    if condition == "lost":
        current.claim.lost = True
    run = (
        None
        if condition == "missing_run"
        else SimpleNamespace(status="cancelled" if condition == "terminal" else "running")
    )
    node = (
        None
        if condition == "missing_node"
        else SimpleNamespace(status="cancelled" if condition == "cancelled_node" else "running")
    )
    attempt = (
        None
        if condition == "missing_attempt"
        else SimpleNamespace(attempt_no=2 if condition == "later_attempt" else 1)
    )
    with (
        patch.object(
            questions.workflow_run_repo, "get_run_by_id_for_update", AsyncMock(return_value=run)
        ),
        patch.object(
            questions.workflow_run_repo,
            "get_node_run_by_id_for_update",
            AsyncMock(return_value=node),
        ),
        patch.object(
            questions.workflow_run_repo, "get_latest_attempt", AsyncMock(return_value=attempt)
        ),
        pytest.raises(BadRequestError, match="no longer accepts"),
    ):
        await questions.link_agent_run(MagicMock(), current, MagicMock())


async def test_admitting_a_child_records_ownership_before_the_model_starts():
    current = _dispatch()
    child = SimpleNamespace(id=uuid.uuid4())
    with (
        patch.object(
            questions.workflow_run_repo,
            "get_run_by_id_for_update",
            AsyncMock(return_value=SimpleNamespace(status="running")),
        ),
        patch.object(
            questions.workflow_run_repo,
            "get_node_run_by_id_for_update",
            AsyncMock(return_value=SimpleNamespace(status="running")),
        ),
        patch.object(
            questions.workflow_run_repo,
            "get_latest_attempt",
            AsyncMock(return_value=SimpleNamespace(attempt_no=1)),
        ),
        patch.object(questions.workflow_run_repo, "update_node_run", AsyncMock()) as update,
        patch.object(questions.workflow_run_repo, "link_attempt_agent_run", AsyncMock()) as link,
        context.dispatching_as(current) as scope,
    ):
        await questions.link_agent_run(MagicMock(), current, child)
        assert scope.waiting_agent_run_id == child.id
        assert update.await_args.kwargs["update_data"] == {"waiting_agent_run_id": child.id}
        assert link.await_args.kwargs["agent_run_id"] == child.id


@pytest.mark.parametrize("condition", ["anonymous", "key", "other_user", "public", "terminal"])
async def test_questions_are_hidden_from_everyone_except_the_signed_in_person_asked(condition):
    current = _dispatch()
    ctx = current.auth
    if condition == "anonymous":
        ctx = dataclasses.replace(ctx, user_id=None)
    if condition == "key":
        ctx = dataclasses.replace(ctx, api_key_id=uuid.uuid4())
    run = SimpleNamespace(
        execution_principal_user_id=uuid.uuid4()
        if condition == "other_user"
        else current.auth.user_id,
        public_origin=condition == "public",
        status=WorkflowRunStatus.CANCELLED
        if condition == "terminal"
        else WorkflowRunStatus.WAITING_FOR_USER,
    )
    assert await questions.read(MagicMock(), ctx, run) == []


@pytest.mark.parametrize(
    "condition", ["no_child_id", "missing_child", "answered_child", "no_questions"]
)
async def test_question_listing_skips_removed_answered_and_unavailable_children(condition):
    ctx = _dispatch().auth
    run = SimpleNamespace(
        id=uuid.uuid4(),
        status="waiting_for_user",
        public_origin=False,
        execution_principal_user_id=ctx.user_id,
    )
    node = SimpleNamespace(
        id=uuid.uuid4(), waiting_agent_run_id=None if condition == "no_child_id" else uuid.uuid4()
    )
    child = (
        None
        if condition == "missing_child"
        else SimpleNamespace(
            id=uuid.uuid4(),
            status="awaiting_answer",
            paused_state={"question_results": {"q1": "declined"}}
            if condition == "answered_child"
            else {},
        )
    )
    with (
        patch.object(
            questions.workflow_run_repo, "list_question_waits", AsyncMock(return_value=[node])
        ),
        patch.object(questions.agent_run_repo, "get_run", AsyncMock(return_value=child)),
        patch("app.services.agent_runner.AgentRunnerService") as runner,
    ):
        runner.return_value.parked_questions = AsyncMock(return_value=[])
        assert await questions.read(MagicMock(), ctx, run) == []


@pytest.mark.parametrize(
    "condition", ["missing_run", "terminal_run", "missing_node", "other_run_node"]
)
async def test_answers_refuse_rows_that_changed_since_the_authorized_read(condition):
    from app.services.workflow_execution import WorkflowExecutionService
    from app.services.workflow_execution.exceptions import (
        WorkflowRunAlreadyTerminalError,
        WorkflowRunNotFoundError,
        WorkflowStepNotFoundError,
    )

    ctx = _dispatch().auth
    run_id, node_id = uuid.uuid4(), uuid.uuid4()
    run = SimpleNamespace(
        id=run_id, execution_principal_user_id=ctx.user_id, public_origin=False, status="running"
    )
    locked = (
        None
        if condition == "missing_run"
        else SimpleNamespace(
            id=run_id, status="cancelled" if condition == "terminal_run" else "waiting_for_user"
        )
    )
    node = (
        None
        if condition == "missing_node"
        else SimpleNamespace(
            workflow_run_id=uuid.uuid4() if condition == "other_run_node" else run_id
        )
    )
    expected = (
        WorkflowRunNotFoundError
        if condition == "missing_run"
        else WorkflowRunAlreadyTerminalError
        if condition == "terminal_run"
        else WorkflowStepNotFoundError
    )
    with (
        patch.object(WorkflowExecutionService, "_load", AsyncMock(return_value=run)),
        patch.object(
            questions.workflow_run_repo, "get_run_for_update", AsyncMock(return_value=locked)
        ),
        patch.object(
            questions.workflow_run_repo,
            "get_node_run_by_id_for_update",
            AsyncMock(return_value=node),
        ),
        pytest.raises(expected),
    ):
        await WorkflowExecutionService(MagicMock()).answer_questions(ctx, run_id, node_id, {})


async def test_a_standalone_agent_question_has_no_workflow_answer_route():
    from app.services.workflow_execution import WorkflowExecutionService

    with patch.object(
        questions.workflow_run_repo, "find_node_run_for_agent_run", AsyncMock(return_value=None)
    ):
        assert (
            await WorkflowExecutionService(MagicMock()).answer_agent_questions(
                _dispatch().auth, uuid.uuid4(), {}
            )
            is None
        )


async def test_a_removed_child_cannot_make_a_wait_ready_to_resume():
    from app.services.workflow_execution.approval_wake import ready_to_resume

    assert not await ready_to_resume(
        MagicMock(), SimpleNamespace(waiting_agent_run_id=None), organization_id=uuid.uuid4()
    )


async def test_a_question_wait_without_a_durable_child_needs_attention():
    from app.services.workflow_execution import dispatcher
    from app.workflows.contracts.results import Waiting

    with (
        patch.object(dispatcher.workflow_run_repo, "update_node_run", AsyncMock()) as update,
        patch.object(dispatcher.events, "append", AsyncMock()),
        patch.object(dispatcher, "refresh_run_status", AsyncMock()),
    ):
        await dispatcher._settle_waiting(
            MagicMock(),
            run=MagicMock(),
            node_run=MagicMock(),
            attempt=MagicMock(),
            result=Waiting(reason="question", resume_token="unused"),
            waiting_agent_run_id=None,
            now=datetime.now(UTC),
        )
        assert update.await_args.kwargs["update_data"]["status"] == "needs_attention"
