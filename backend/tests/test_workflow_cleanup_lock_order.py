"""Ending a run with several parked agent steps audits only after its last row lock.

`record_audit` takes the organization's audit-chain lock and holds it to the end of
the transaction, so it must follow every row lock (`app.core.audit.record_audit`).
Stopping the parked agent runs one by one, audit and all, would take that lock
between two claims and close an ABBA cycle with a concurrent decision.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.db.models.agent_run import RunStatus
from app.services import agent_runner
from app.services.workflow_execution import cleanup

pytestmark = pytest.mark.anyio

_RUNNER = agent_runner.AgentRunnerService
NOW = agent_runner.datetime.now(agent_runner.UTC)


def _parked(run_id: UUID, organization_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        organization_id=organization_id,
        status=RunStatus.AWAITING_APPROVAL.value,
        paused_state=None,
        conversation_id=None,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0,
        cost_is_partial=False,
    )


async def test_every_parked_run_is_claimed_before_the_first_audit_entry() -> None:
    org = uuid4()
    low, high = sorted([uuid4(), uuid4()])
    node_runs = [
        SimpleNamespace(id=uuid4(), waiting_agent_run_id=high),
        SimpleNamespace(id=uuid4(), waiting_agent_run_id=None),
        SimpleNamespace(id=uuid4(), waiting_agent_run_id=low),
    ]
    run = SimpleNamespace(id=uuid4(), organization_id=org)
    order: list[tuple[str, Any]] = []

    async def claim(_db: Any, run_id: UUID, *, organization_id: UUID) -> SimpleNamespace:
        order.append(("claim", run_id))
        return _parked(run_id, organization_id)

    async def audit(_db: Any, **kwargs: Any) -> None:
        order.append(("audit", UUID(kwargs["target_id"])))

    async def row_work(*_args: Any, **_kwargs: Any) -> None:
        order.append(("row", None))

    with (
        patch.object(agent_runner.agent_run_repo, "claim_parked_run", claim),
        patch.object(agent_runner.agent_run_repo, "expire_pending_approvals", row_work),
        patch.object(agent_runner.agent_run_repo, "finish_run", row_work),
        patch.object(agent_runner, "record_audit", audit),
        patch.object(agent_runner, "AgentRunnerService", _runner),
        patch.object(cleanup.workflow_run_repo, "update_node_run", row_work),
        patch.object(cleanup.events, "append", row_work),
    ):
        await cleanup._cancel_nodes(MagicMock(), run=run, node_runs=node_runs, now=NOW)

    kinds = [kind for kind, _ in order]
    assert kinds.count("claim") == 2 and kinds.count("audit") == 2
    last_claim = max(i for i, kind in enumerate(kinds) if kind == "claim")
    first_audit = min(i for i, kind in enumerate(kinds) if kind == "audit")
    assert last_claim < first_audit
    assert [rid for kind, rid in order if kind == "claim"] == [low, high]
    assert [rid for kind, rid in order if kind == "audit"] == [low, high]


def _runner(db: Any) -> agent_runner.AgentRunnerService:
    # `patch` replaces the module's name, so the class is taken from the constant below.
    service = object.__new__(_RUNNER)
    service.db = db
    service.transcript = SimpleNamespace(record=AsyncMock())  # type: ignore[assignment]
    return service
