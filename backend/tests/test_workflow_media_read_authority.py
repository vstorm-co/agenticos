"""The existing run authorization precedes every page of media journal summaries."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.permissions import Perm
from app.db.models.workflow_run import NodeRun
from app.schemas.workflow_media import WorkflowMediaOperationRead
from app.services.workflow_execution import facade
from app.services.workflow_execution.exceptions import WorkflowRunNotFoundError
from app.services.workflow_media_read import WorkflowMediaReadService
from tests.test_workflow_execution_facade import _ctx, _run_row, _workflow

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("boundary", ["missing_run", "denied_workflow", "allowed"])
async def test_media_summaries_obey_run_authority_and_the_requested_node_page(
    monkeypatch, boundary
):
    ctx = _ctx()
    run = _run_row()
    workflow = _workflow(id=run.workflow_id)
    node = NodeRun(
        id=uuid4(),
        node_instance_id=uuid4(),
        scope_path=[],
        status="needs_attention",
        waiting_reason=None,
    )
    monkeypatch.setattr(
        facade.workflow_run_repo,
        "get_run",
        AsyncMock(return_value=None if boundary == "missing_run" else run),
    )
    monkeypatch.setattr(facade.workflow_repo, "get", AsyncMock(return_value=workflow))
    access = AsyncMock(return_value=boundary == "allowed")
    monkeypatch.setattr(facade, "resolve_access", access)
    page = AsyncMock(return_value=([node], 17))
    monkeypatch.setattr(facade.workflow_run_repo, "list_node_runs_page", page)
    monkeypatch.setattr(facade.workflow_run_repo, "list_attempts_of", AsyncMock(return_value=[]))
    monkeypatch.setattr(facade.workflow_approval_repo, "step_decisions", AsyncMock(return_value=[]))
    summary = WorkflowMediaOperationRead(
        operation_id=uuid4(),
        phase="unknown",
        held_usd=Decimal("2"),
        incurred_usd=Decimal("0.5"),
        booked_usd=Decimal("0.5"),
        cost_source="catalog_estimate",
        accounting_complete=False,
        node_unresolved_usd=Decimal("3"),
        has_receipt=False,
        retry_effect="reconciliation_required",
    )
    reads = AsyncMock(return_value={node.id: summary})
    monkeypatch.setattr(WorkflowMediaReadService, "for_nodes", reads)
    db = MagicMock()
    service = facade.WorkflowExecutionService(db)
    if boundary != "allowed":
        with pytest.raises(WorkflowRunNotFoundError):
            await service.node_runs(ctx, run.id, skip=4, limit=1)
        page.assert_not_awaited()
        reads.assert_not_awaited()
        return
    result = await service.node_runs(ctx, run.id, skip=4, limit=1)
    assert result.total == 17 and len(result.items) == 1
    assert result.items[0].media_operation == summary
    page.assert_awaited_once_with(
        db, workflow_run_id=run.id, organization_id=ctx.organization_id, skip=4, limit=1
    )
    reads.assert_awaited_once_with(
        organization_id=ctx.organization_id, workflow_run_id=run.id, node_run_ids=[node.id]
    )
    assert access.await_args.args[3] is Perm.WORKFLOWS_VIEW
