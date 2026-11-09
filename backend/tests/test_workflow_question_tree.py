"""A caller sees only questions from visible synchronous calls for its person."""

import dataclasses
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext
from app.db.models.workflow_run import WorkflowRun
from app.schemas.workflow_run import WorkflowQuestionRead
from app.services.workflow_execution import question_tree
from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError

pytestmark = pytest.mark.anyio


def _run(ctx: AuthContext) -> WorkflowRun:
    return WorkflowRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        execution_principal_user_id=ctx.user_id,
        public_origin=False,
        status="running",
    )


def _person() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


@pytest.mark.parametrize("condition", ["anonymous", "key", "other_user", "public", "terminal"])
@pytest.mark.security
async def test_a_question_tree_is_only_read_for_the_original_person(condition: str) -> None:
    ctx = _person()
    run = _run(ctx)
    if condition == "anonymous":
        ctx = dataclasses.replace(ctx, user_id=None)
    elif condition == "key":
        ctx = dataclasses.replace(ctx, api_key_id=uuid.uuid4())
    elif condition == "other_user":
        ctx = dataclasses.replace(ctx, user_id=uuid.uuid4())
    elif condition == "public":
        run.public_origin = True
    else:
        run.status = "cancelled"

    load = AsyncMock()
    assert (
        await question_tree.read(
            MagicMock(), ctx, run, load=load, can_answer=AsyncMock(return_value=True)
        )
        == []
    )
    load.assert_not_awaited()


@pytest.mark.security
async def test_hidden_or_differently_owned_children_are_skipped_and_cycles_are_bounded() -> None:
    ctx = _person()
    root, child, hidden, public, other, deeper = (_run(ctx) for _ in range(6))
    public.public_origin = True
    other.execution_principal_user_id = uuid.uuid4()
    card = WorkflowQuestionRead(
        workflow_run_id=child.id, node_run_id=uuid.uuid4(), agent_run_id=uuid.uuid4(), questions=[]
    )

    async def load(run_id: uuid.UUID) -> WorkflowRun:
        if run_id == hidden.id:
            raise WorkflowRunNotFoundError(run_id=run_id)
        return deeper if run_id == deeper.id else child

    async def children(
        _db: object, *, workflow_run_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[WorkflowRun]:
        assert organization_id == ctx.organization_id
        return [child, child, hidden, public, other] if workflow_run_id == root.id else [deeper]

    with (
        patch.object(
            question_tree.workflow_run_repo, "list_waited_child_runs", side_effect=children
        ),
        patch.object(question_tree.questions, "read", new=AsyncMock(side_effect=[[], [card]])),
        patch.object(question_tree, "MAX_CALL_DEPTH", 1),
    ):
        assert await question_tree.read(
            MagicMock(), ctx, root, load=load, can_answer=AsyncMock(return_value=True)
        ) == [card]


async def test_a_child_read_failure_is_not_mistaken_for_hidden_access() -> None:
    ctx = _person()
    root, child = _run(ctx), _run(ctx)
    with (
        patch.object(
            question_tree.workflow_run_repo,
            "list_waited_child_runs",
            new=AsyncMock(return_value=[child]),
        ),
        patch.object(question_tree.questions, "read", new=AsyncMock(return_value=[])),
        pytest.raises(RuntimeError, match="database failed"),
    ):
        await question_tree.read(
            MagicMock(),
            ctx,
            root,
            load=AsyncMock(side_effect=RuntimeError("database failed")),
            can_answer=AsyncMock(return_value=True),
        )


@pytest.mark.security
async def test_each_visible_workflow_needs_its_own_current_run_permission() -> None:
    ctx = _person()
    root, child = _run(ctx), _run(ctx)
    card = WorkflowQuestionRead(
        workflow_run_id=child.id, node_run_id=uuid.uuid4(), agent_run_id=uuid.uuid4(), questions=[]
    )
    with (
        patch.object(
            question_tree.workflow_run_repo,
            "list_waited_child_runs",
            AsyncMock(side_effect=[[child], []]),
        ),
        patch.object(question_tree.questions, "read", AsyncMock(return_value=[card])) as read,
    ):
        result = await question_tree.read(
            MagicMock(),
            ctx,
            root,
            load=AsyncMock(return_value=child),
            can_answer=AsyncMock(side_effect=[False, True]),
        )
    assert result == [card]
    assert read.await_args is not None and read.await_args.args[2].id == child.id
    assert read.await_count == 1
