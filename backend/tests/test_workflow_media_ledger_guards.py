"""Late fee reconciliation must retain the canonical tenant, run and attempt."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.workflow_execution import dispatcher, reconciler

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("boundary", ["missing_attempt", "other_node", "other_organization"])
async def test_a_fee_cannot_be_booked_against_a_missing_or_unrelated_original_attempt(
    monkeypatch, boundary
):
    db = AsyncMock()
    run = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    node = SimpleNamespace(id=uuid4())
    operation = SimpleNamespace(
        id=uuid4(), origin_attempt_id=uuid4(), incurred_usd=Decimal("0.3"), booked_usd=Decimal(0)
    )
    origin = SimpleNamespace(
        id=operation.origin_attempt_id,
        node_run_id=uuid4() if boundary == "other_node" else node.id,
        organization_id=uuid4() if boundary == "other_organization" else run.organization_id,
    )
    monkeypatch.setattr(
        dispatcher.media_repo, "unbooked_for_node", AsyncMock(return_value=[operation])
    )
    monkeypatch.setattr(
        dispatcher.workflow_run_repo,
        "get_attempt",
        AsyncMock(return_value=None if boundary == "missing_attempt" else origin),
    )
    book, mark_booked = AsyncMock(), AsyncMock()
    monkeypatch.setattr(dispatcher, "_book_cost", book)
    monkeypatch.setattr(dispatcher.media_repo, "change", mark_booked)
    with pytest.raises(RuntimeError, match="lost its canonical attempt"):
        await dispatcher.book_media_costs(db, run=run, node_run=node)
    book.assert_not_awaited()
    mark_booked.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "boundary",
    ["busy_organization", "missing_run", "missing_node", "other_organization", "other_run"],
)
async def test_a_fee_sweep_leaves_busy_or_changed_scope_unbooked(monkeypatch, boundary):
    db = AsyncMock()
    run = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    node = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4() if boundary == "other_organization" else run.organization_id,
        workflow_run_id=uuid4() if boundary == "other_run" else run.id,
    )
    monkeypatch.setattr(
        reconciler.media_repo,
        "unbooked_nodes",
        AsyncMock(return_value=[(run.organization_id, run.id, node.id)]),
    )
    monkeypatch.setattr(
        reconciler, "try_hold_subject", AsyncMock(return_value=boundary != "busy_organization")
    )
    lock_run = AsyncMock(return_value=None if boundary == "missing_run" else run)
    lock_node = AsyncMock(return_value=None if boundary == "missing_node" else node)
    monkeypatch.setattr(reconciler.workflow_run_repo, "try_lock_run", lock_run)
    monkeypatch.setattr(reconciler.workflow_run_repo, "get_node_run_by_id_for_update", lock_node)
    book = AsyncMock()
    monkeypatch.setattr(dispatcher, "book_media_costs", book)
    assert await reconciler.WorkflowReconcilerService(db).book_pending_media_costs(limit=3) == 0
    book.assert_not_awaited()
    db.execute.assert_not_awaited()
    if boundary == "busy_organization":
        lock_run.assert_not_awaited()
    if boundary in {"busy_organization", "missing_run"}:
        lock_node.assert_not_awaited()
