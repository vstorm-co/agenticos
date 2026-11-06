"""Durable timers, corrections, restarts and cancellation share the workflow engine."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.db.models.workflow_run import NodeRun
from app.schemas.reply_expectation import ReplyExpectation, ReplyExpectationEdit
from app.services.portals.reply_metadata import ReplyMessage
from app.services.workflow_execution import WorkflowExecutionService, dispatch_queue
from app.services.workflow_execution.exceptions import (
    WorkflowRunAlreadyTerminalError,
    WorkflowRunNotFoundError,
    WorkflowStepNotFoundError,
    WorkflowStepNotResolvableError,
)
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, drive
from tests.integration.workflow_run_support import seed_run as seed_workflow

pytestmark = pytest.mark.anyio


async def seed(
    engine: AsyncEngine, *, overdue: bool = False
) -> tuple[SeededRun, NodeInstance, ReplyExpectationEdit]:
    now = datetime.now(UTC)
    body = ReplyExpectationEdit(
        thread_id="t",
        expected_sender="alice@example.com",
        not_before=now - timedelta(hours=2),
        deadline=now + timedelta(seconds=-10 if overdue else 3600),
    )

    def node(kind: str) -> NodeInstance:
        return NodeInstance(
            id=uuid4(), definition_id=kind, definition_version=1, layout=NodePosition(x=0, y=0)
        )

    entry, wait, out = node("core.input"), node("flow.await_reply"), node("core.output")
    wait = wait.model_copy(
        update={"config": {"provider": "google", "connection_id": str(uuid4()), "poll_seconds": 60}}
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, wait, out),
        edges=(
            Edge(
                id=uuid4(),
                source_node_id=entry.id,
                source_port="out",
                target_node_id=wait.id,
                target_port="in",
            ),
            Edge(
                id=uuid4(),
                source_node_id=wait.id,
                source_port="reply",
                target_node_id=out.id,
                target_port="in",
            ),
            Edge(
                id=uuid4(),
                source_node_id=wait.id,
                source_port="deadline",
                target_node_id=out.id,
                target_port="in",
            ),
        ),
        bindings=(
            *tuple(
                Binding(target_node_id=wait.id, target_field=key, source=LiteralValue(value=value))
                for key, value in body.model_dump(
                    mode="json", exclude={"paused", "review_mailbox"}
                ).items()
            ),
            Binding(
                target_node_id=out.id,
                target_field="structured",
                source=NodeOutputRef(node_id=wait.id, port="deadline" if overdue else "reply"),
            ),
        ),
    )
    return await seed_workflow(engine, graph), wait, body


@asynccontextmanager
async def sessions(seeded: SeededRun) -> AsyncIterator[AsyncSession]:
    async with seeded.factory() as db:
        yield db
        await db.commit()


async def step_of(seeded: SeededRun, wait: NodeInstance) -> NodeRun:
    async with seeded.factory() as db:
        return (
            await db.scalars(
                select(NodeRun).where(
                    NodeRun.workflow_run_id == seeded.run.id, NodeRun.node_instance_id == wait.id
                )
            )
        ).one()


async def wake(seeded: SeededRun, step: NodeRun) -> None:
    async with seeded.factory() as db:
        await dispatch_queue.wake_now(db, run=seeded.run, node_run_id=step.id)
        await db.commit()


async def test_restart_keeps_account_and_expectation_then_continues_once(engine: AsyncEngine):
    seeded, wait, body = await seed(engine)
    token = AsyncMock(return_value=(uuid4(), SecretStr("token")))
    read = AsyncMock(return_value=())
    with (
        patch(
            "app.workflows.nodes.flow_await_reply._handler.get_worker_db_context",
            lambda: sessions(seeded),
        ),
        patch("app.services.mcp_connection.McpConnectionService.reply_mailbox_token", token),
        patch("app.services.portals.reply_metadata.MailReplyMetadataClient.read", read),
    ):
        assert (await drive(seeded)).status == "running"
        step = await step_of(seeded, wait)
        assert step.status == "waiting"
        state = ReplyExpectation.model_validate(step.resume_payload)
        assert state.expected_sender == body.expected_sender
        async with seeded.factory() as db:
            listing = await WorkflowExecutionService(db).node_runs(seeded.ctx, seeded.run.id)
            assert (
                next(row for row in listing.items if row.id == step.id).reply_expectation == state
            )
        read.return_value = (
            ReplyMessage(
                message_id="r",
                thread_id="t",
                sender="alice@example.com",
                received_at=datetime.now(UTC),
                authenticated=True,
            ),
        )
        await wake(seeded, step)
        ended = await drive(seeded)
        assert ended.status == "succeeded"
        assert token.call_args.kwargs["authorization_generation"] == state.authorization_generation
        assert (await drive(seeded)).status == "succeeded"
        assert read.await_count == 2


async def test_pause_correction_and_resume_make_no_mailbox_calls_while_paused(engine: AsyncEngine):
    seeded, wait, body = await seed(engine)
    read = AsyncMock(return_value=())
    with (
        patch(
            "app.workflows.nodes.flow_await_reply._handler.get_worker_db_context",
            lambda: sessions(seeded),
        ),
        patch(
            "app.services.mcp_connection.McpConnectionService.reply_mailbox_token",
            AsyncMock(return_value=(uuid4(), SecretStr("token"))),
        ),
        patch("app.services.portals.reply_metadata.MailReplyMetadataClient.read", read),
    ):
        await drive(seeded)
        step = await step_of(seeded, wait)
        async with seeded.factory() as db:
            state = await WorkflowExecutionService(db).edit_reply_expectation(
                seeded.ctx,
                seeded.run.id,
                step.id,
                body.model_copy(update={"paused": True, "expected_sender": "bob@example.com"}),
            )
            await db.commit()
        assert state.paused and state.expected_sender == "bob@example.com"
        assert (await drive(seeded)).status == "running"
        assert read.await_count == 1
        async with seeded.factory() as db:
            await WorkflowExecutionService(db).edit_reply_expectation(
                seeded.ctx,
                seeded.run.id,
                step.id,
                body.model_copy(update={"expected_sender": "bob@example.com"}),
            )
            await db.commit()
        await drive(seeded)
        assert read.await_count == 2
        async with seeded.factory() as db:
            await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
            await db.commit()
        assert (await drive(seeded)).status == "cancelled"
        assert read.await_count == 2


async def test_foreign_run_and_executing_step_cannot_be_corrected(engine: AsyncEngine):
    seeded, wait, body = await seed(engine)
    read = AsyncMock(return_value=())
    with (
        patch(
            "app.workflows.nodes.flow_await_reply._handler.get_worker_db_context",
            lambda: sessions(seeded),
        ),
        patch(
            "app.services.mcp_connection.McpConnectionService.reply_mailbox_token",
            AsyncMock(return_value=(uuid4(), SecretStr("token"))),
        ),
        patch("app.services.portals.reply_metadata.MailReplyMetadataClient.read", read),
    ):
        await drive(seeded)
    step = await step_of(seeded, wait)
    async with seeded.factory() as db:
        foreign = AuthContext(user_id=seeded.principal.id, organization_id=uuid4(), role="owner")
        with pytest.raises(WorkflowRunNotFoundError):
            await WorkflowExecutionService(db).edit_reply_expectation(
                foreign, seeded.run.id, step.id, body
            )
        step.status = "running"
        db.add(step)
        await db.flush()
        with pytest.raises(WorkflowStepNotResolvableError):
            await WorkflowExecutionService(db).edit_reply_expectation(
                seeded.ctx, seeded.run.id, step.id, body
            )


@pytest.mark.parametrize("replied", [False, True])
async def test_final_check_prefers_an_existing_timely_reply_to_deadline(
    engine: AsyncEngine, replied: bool
):
    seeded, wait, body = await seed(engine, overdue=True)
    reply = ReplyMessage(
        message_id="r",
        thread_id="t",
        sender="alice@example.com",
        authenticated=True,
        received_at=body.deadline - timedelta(seconds=1),
    )
    with (
        patch(
            "app.workflows.nodes.flow_await_reply._handler.get_worker_db_context",
            lambda: sessions(seeded),
        ),
        patch(
            "app.services.mcp_connection.McpConnectionService.reply_mailbox_token",
            AsyncMock(return_value=(uuid4(), SecretStr("token"))),
        ),
        patch(
            "app.services.portals.reply_metadata.MailReplyMetadataClient.read",
            AsyncMock(return_value=(reply,) if replied else ()),
        ),
    ):
        await drive(seeded)
        async with seeded.factory() as db:
            listing = await WorkflowExecutionService(db).node_runs(seeded.ctx, seeded.run.id)
        output = next(row.output for row in listing.items if row.node_instance_id == wait.id)
        assert output is not None and output["branch"] == ("reply" if replied else "deadline")


@pytest.mark.parametrize(
    "variant",
    [
        "permission",
        "deleted_run",
        "ended",
        "other_step",
        "no_state",
        "too_long",
        "review_missing",
        "review_replaced",
        "review_disabled",
        "review_ok",
        "review_attention",
    ],
)
async def test_corrections_refuse_invalid_state_and_require_explicit_source_review(
    engine: AsyncEngine, variant: str
):
    seeded, wait, body = await seed(engine)
    with (
        patch(
            "app.workflows.nodes.flow_await_reply._handler.get_worker_db_context",
            lambda: sessions(seeded),
        ),
        patch(
            "app.services.mcp_connection.McpConnectionService.reply_mailbox_token",
            AsyncMock(return_value=(uuid4(), SecretStr("token"))),
        ),
        patch(
            "app.services.portals.reply_metadata.MailReplyMetadataClient.read",
            AsyncMock(return_value=()),
        ),
    ):
        await drive(seeded)
    step = await step_of(seeded, wait)
    state = ReplyExpectation.model_validate(step.resume_payload)
    async with seeded.factory() as db:
        service = WorkflowExecutionService(db)
        if variant == "review_attention":
            from app.db.models.workflow_run import NodeRunStatus

            step.status = NodeRunStatus.NEEDS_ATTENTION.value
            db.add(step)
            await db.flush()
        if variant == "permission":
            with (
                patch.object(service, "_may_resolve", AsyncMock(return_value=False)),
                pytest.raises(AuthorizationError),
            ):
                await service.edit_reply_expectation(seeded.ctx, seeded.run.id, step.id, body)
        elif variant == "deleted_run":
            with (
                patch(
                    "app.repositories.workflow_run.get_run_for_update", AsyncMock(return_value=None)
                ),
                pytest.raises(WorkflowRunNotFoundError),
            ):
                await service.edit_reply_expectation(seeded.ctx, seeded.run.id, step.id, body)
        elif variant == "ended":
            await service.cancel(seeded.ctx, seeded.run.id)
            with pytest.raises(WorkflowRunAlreadyTerminalError):
                await service.edit_reply_expectation(seeded.ctx, seeded.run.id, step.id, body)
        elif variant == "other_step":
            with pytest.raises(WorkflowStepNotFoundError):
                await service.edit_reply_expectation(seeded.ctx, seeded.run.id, uuid4(), body)
        elif variant == "no_state":
            step.resume_payload = None
            db.add(step)
            await db.flush()
            with pytest.raises(WorkflowStepNotResolvableError):
                await service.edit_reply_expectation(seeded.ctx, seeded.run.id, step.id, body)
        elif variant == "too_long":
            with pytest.raises(WorkflowStepNotResolvableError):
                await service.edit_reply_expectation(
                    seeded.ctx,
                    seeded.run.id,
                    step.id,
                    body.model_copy(update={"deadline": datetime.now(UTC) + timedelta(days=31)}),
                )
        else:
            grant = (
                None
                if variant == "review_missing"
                else McpConnection(
                    id=uuid4() if variant == "review_replaced" else state.connection_id,
                    authorization_generation=uuid4(),
                    is_enabled=variant != "review_disabled",
                )
            )
            with patch(
                "app.services.mcp_connection.McpConnectionService.get_org_portal_grant",
                AsyncMock(return_value=grant),
            ):
                reviewed = body.model_copy(update={"review_mailbox": True})
                if variant in {"review_ok", "review_attention"}:
                    updated = await service.edit_reply_expectation(
                        seeded.ctx, seeded.run.id, step.id, reviewed
                    )
                    assert (
                        grant is not None
                        and updated.authorization_generation == grant.authorization_generation
                    )
                    assert updated.connection_id == state.connection_id
                else:
                    with pytest.raises(NotFoundError):
                        await service.edit_reply_expectation(
                            seeded.ctx, seeded.run.id, step.id, reviewed
                        )
