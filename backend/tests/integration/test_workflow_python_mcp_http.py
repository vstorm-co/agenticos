"""Python action continuations over real MCP HTTP and PostgreSQL, without a model."""

from dataclasses import replace
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.background import discard_deferred
from app.db.models.mcp_connection import McpConnection
from app.db.models.workflow_approval import WorkflowApproval
from app.db.models.workflow_run import WorkflowRun
from app.services.workflow_execution.approvals import WorkflowApprovalService, wake_approval_step
from app.services.workflow_execution.facade import WorkflowExecutionService
from tests.integration.test_workflow_python_nodes import _chain, _node
from tests.integration.workflow_run_support import SeededRun, drive, seed_run
from tests.test_workflow_mcp_call_http import _Endpoint
from tests.test_workflow_mcp_call_http import endpoint as endpoint

pytestmark = pytest.mark.anyio


async def _script(
    engine: AsyncEngine,
    endpoint: _Endpoint,
    code: str,
    *,
    tool: str = "slow_read",
    approval: Literal["writes", "all", "none"] = "writes",
    on_tool_error: Literal["fail", "complete"] = "fail",
) -> SeededRun:
    connection_id = uuid4()
    step = _node(
        "code.python.actions",
        {
            "code": code,
            "actions": {
                "lookup": {
                    "type": "mcp.call",
                    "config": {
                        "connection_id": str(connection_id),
                        "tool": tool,
                        "approval": approval,
                        "on_tool_error": on_tool_error,
                    },
                }
            },
        },
    )
    seeded = await seed_run(engine, _chain(step))
    async with seeded.factory() as db:
        db.add(
            McpConnection(
                id=connection_id,
                organization_id=seeded.org.id,
                scope="org",
                name="local-tools",
                url=endpoint.url,
                last_tools=[{"name": tool}],
                allowed_tools=[tool],
            )
        )
        await db.commit()
    return seeded


@pytest.mark.parametrize("gated", [False, True], ids=["read", "approved-write"])
async def test_each_python_call_gets_its_own_real_mcp_result(
    engine: AsyncEngine, endpoint: _Endpoint, gated: bool
) -> None:
    seeded = await _script(
        engine,
        endpoint,
        "answers = []\nfor i in range(2):\n"
        "    answers.append(lookup(arguments={'delay_seconds': 0})['structured'])\nanswers",
        tool="slow_write" if gated else "slow_read",
        approval="all" if gated else "writes",
    )
    finished = await drive(seeded)
    decisions: list[UUID] = []
    if gated:
        for index in range(2):
            assert finished.status == "waiting_approval"
            assert endpoint.attempts == index
            async with seeded.factory() as db:
                request = await db.scalar(
                    select(WorkflowApproval).where(
                        WorkflowApproval.workflow_run_id == seeded.run.id,
                        WorkflowApproval.status == "pending",
                    )
                )
                assert request is not None
                decisions.append(request.node_run_id)
                await WorkflowApprovalService(db).decide(seeded.ctx, request.id, approved=True)
                await db.commit()
                discard_deferred(db)
            await wake_approval_step(request.node_run_id, organization_id=seeded.org.id)
            finished = await drive(seeded)
        assert len(set(decisions)) == 2
    assert finished.status == "succeeded", finished.error
    assert finished.output is not None
    assert finished.output["structured"]["result"] == [{"ok": True}, {"ok": True}]
    assert endpoint.attempts == 2


async def test_retry_of_a_script_failure_does_not_repeat_a_real_mcp_write(
    engine: AsyncEngine, endpoint: _Endpoint
) -> None:
    seeded = await _script(
        engine,
        endpoint,
        "lookup(arguments={'delay_seconds': 0})\n1 / 0",
        tool="slow_write",
        approval="none",
    )
    original = await drive(seeded)
    assert original.error is not None and original.error["code"] == "PYTHON_ERROR"
    assert endpoint.attempts == 1
    async with seeded.factory() as db:
        retried = await WorkflowExecutionService(db).retry(seeded.ctx, original.id)
        await db.commit()
        row = await db.get(WorkflowRun, retried.id)
        assert row is not None
    finished = await drive(replace(seeded, run=row))
    assert finished.error is not None and finished.error["code"] == "PYTHON_ERROR"
    assert endpoint.attempts == 1


@pytest.mark.parametrize("on_tool_error", ["fail", "complete"])
async def test_an_mcp_input_error_follows_the_bound_error_policy(
    engine: AsyncEngine,
    endpoint: _Endpoint,
    on_tool_error: Literal["fail", "complete"],
) -> None:
    seeded = await _script(
        engine,
        endpoint,
        "answer = lookup(arguments={'delay_seconds': 'invalid'})\nanswer['is_error']",
        on_tool_error=on_tool_error,
    )
    finished = await drive(seeded)
    if on_tool_error == "complete":
        assert finished.status == "succeeded", finished.error
        assert finished.output is not None and finished.output["structured"]["result"] is True
    else:
        assert finished.status == "failed"
        assert finished.error is not None and finished.error["code"] == "MCP_TOOL_ERROR"
    assert endpoint.attempts == 0
