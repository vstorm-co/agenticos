"""Explicit refusal paths never become a successful no-reply branch."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExternalServiceError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.db.models.workflow_run import NodeRun, WorkflowRun
from app.schemas.reply_expectation import ReplyExpectation, ReplyExpectationInput
from app.services.reply_expectation import store_expectation
from app.services.workflow_execution.context import DispatchContext, dispatching_as
from app.services.workflow_execution.exceptions import WorkflowInlineStorageLimitError
from app.workflows.contracts.results import Failed
from app.workflows.nodes.flow_await_reply._handler import (
    AwaitReplyConfig,
    AwaitReplyInput,
    handle,
    resource_check,
    routes,
)


class UnrelatedConfig(BaseModel):
    pass


pytestmark = pytest.mark.anyio


async def test_configuration_and_route_contract():
    assert isinstance(await handle(None, None), Failed)
    assert routes(None) == frozenset()
    assert routes({"branch": "reply"}) == frozenset({"reply"})
    assert routes({"branch": "deadline"}) == frozenset({"deadline"})
    assert routes({"branch": "wrong"}) == frozenset()
    with pytest.raises(ValidationError):
        AwaitReplyConfig(provider="google", connection_id=uuid4(), mailbox="shared@example.com")


@pytest.mark.parametrize(
    "variant", ["wrong_config", "missing", "disabled", "other", "forbidden", "allowed"]
)
async def test_publish_checks_the_selected_mailbox(variant: str):
    config = AwaitReplyConfig(provider="outlook", connection_id=uuid4())
    grant = McpConnection(
        id=uuid4() if variant == "other" else config.connection_id, is_enabled=variant != "disabled"
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    with (
        patch(
            "app.services.mcp_connection.McpConnectionService.get_org_portal_grant",
            AsyncMock(return_value=None if variant == "missing" else grant),
        ),
        patch(
            "app.services.mcp_connection.McpConnectionService.get_org_portal_connection",
            AsyncMock(
                side_effect=NotFoundError(message="gone") if variant == "forbidden" else None
            ),
        ),
    ):
        async with AsyncSession() as db:
            result = await resource_check(
                db, ctx, UnrelatedConfig() if variant == "wrong_config" else config
            )
    assert bool(result) == (variant not in ("wrong_config", "allowed"))


@pytest.mark.parametrize(
    ("variant", "code"),
    [
        ("no_run", "REPLY_RUN_ENDED"),
        ("no_step", "REPLY_RUN_ENDED"),
        ("wrong_run", "REPLY_RUN_ENDED"),
        ("ended", "REPLY_RUN_ENDED"),
        ("invalid_state", "REPLY_STATE_INVALID"),
        ("too_long", "REPLY_DEADLINE_TOO_LONG"),
        ("no_token", "REPLY_MAILBOX_UNAVAILABLE"),
        ("not_found", "REPLY_MAILBOX_UNAVAILABLE"),
        ("read_failure", "REPLY_CHECK_FAILED"),
        ("paused_expired", "REPLY_PAUSED_DEADLINE_REACHED"),
    ],
)
async def test_handler_refusals_are_failures(variant: str, code: str):
    now = datetime.now(UTC)
    ctx = DispatchContext(
        organization_id=uuid4(),
        workflow_run_id=uuid4(),
        node_run_id=uuid4(),
        node_instance_id=uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        resumed_agent_run_id=None,
    )
    run = WorkflowRun(
        id=ctx.workflow_run_id,
        status="cancelled" if variant == "ended" else "running",
        organization_id=ctx.organization_id,
        inline_result_bytes=0,
    )
    step = NodeRun(
        id=ctx.node_run_id,
        workflow_run_id=uuid4() if variant == "wrong_run" else run.id,
        created_at=now,
        resume_payload={"bad": "state"} if variant == "invalid_state" else None,
    )
    body = ReplyExpectationInput(
        thread_id="t",
        expected_sender="a@example.com",
        not_before=now - timedelta(hours=1),
        deadline=now + timedelta(days=31 if variant == "too_long" else 1),
    )
    if variant == "paused_expired":
        step.resume_payload = ReplyExpectation(
            **body.model_dump(exclude={"deadline", "not_before"}),
            deadline=now - timedelta(seconds=1),
            not_before=now - timedelta(hours=2),
            provider="outlook",
            connection_id=uuid4(),
            authorization_generation=uuid4(),
            paused=True,
        ).model_dump(mode="json")
    config = AwaitReplyConfig(
        provider="outlook", connection_id=uuid4(), mailbox="shared@example.com"
    )

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession() as db:
            yield db

    with (
        dispatching_as(ctx),
        patch("app.workflows.nodes.flow_await_reply._handler.get_worker_db_context", session),
        patch("app.workflows.nodes.flow_await_reply._handler.hold_subject", AsyncMock()),
        patch("app.workflows.nodes.flow_await_reply._handler.store_expectation", AsyncMock()),
        patch(
            "app.repositories.workflow_run.get_run_for_update",
            AsyncMock(return_value=None if variant == "no_run" else run),
        ),
        patch(
            "app.repositories.workflow_run.get_node_run_by_id_for_update",
            AsyncMock(return_value=None if variant == "no_step" else step),
        ),
        patch(
            "app.services.mcp_connection.McpConnectionService.reply_mailbox_token",
            AsyncMock(
                return_value=None if variant == "no_token" else (uuid4(), SecretStr("token")),
                side_effect=NotFoundError(message="gone") if variant == "not_found" else None,
            ),
        ),
        patch(
            "app.services.portals.reply_metadata.MailReplyMetadataClient.read",
            AsyncMock(side_effect=ExternalServiceError(message="provider failure")),
        ),
    ):
        result = await handle(config, AwaitReplyInput.model_validate(body.model_dump(mode="json")))
    assert isinstance(result, Failed) and result.error.code == code


async def test_expectation_storage_refuses_quota_overflow():
    now = datetime.now(UTC)
    state = ReplyExpectation(
        provider="google",
        connection_id=uuid4(),
        authorization_generation=uuid4(),
        thread_id="t",
        expected_sender="a@example.com",
        not_before=now,
        deadline=now + timedelta(hours=1),
    )
    with patch(
        "app.services.workflow_execution.admission.inline_storage_scope",
        AsyncMock(return_value="run"),
    ):
        async with AsyncSession() as db:
            with pytest.raises(WorkflowInlineStorageLimitError):
                await store_expectation(
                    db,
                    run=WorkflowRun(organization_id=uuid4(), inline_result_bytes=0),
                    step=NodeRun(resume_payload=None),
                    expectation=state,
                )
