"""Where the dispatch tick's transactions actually end, against Postgres.

Structurally `test_run_commit_boundary.py`'s own shape, applied to the
dispatcher's three-phase split (`docs/plans/1788-durable-execution.md`,
"Prefect: a flow per dispatch tick"): only a *second* connection can tell a
flush from a commit, so each phase boundary here is asserted by reading the
row back on a connection that is not the one the phase wrote through.

What each test proves is exactly what a crash at that instant would leave
behind for the reconciler to find - `claim` commits before any attempt
exists, `begin_attempt` commits the `in_flight` row before the handler is
ever called, and `settle`'s result and its downstream dispatch commit
together, never one without the other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    RetryGuarantee,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import dispatcher
from app.services.workflow_execution.reconciler import WorkflowReconcilerService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio


async def _org(db: AsyncSession) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    return org


def _echo_graph() -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={"message": "hi"},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


async def _workflow(db: AsyncSession, org: Organization, graph: WorkflowGraph) -> Workflow:
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name="Echo once",
        status=WorkflowStatus.PUBLISHED.value,
        visibility=Visibility.PRIVATE.value,
        draft_graph=graph.model_dump(mode="json"),
    )
    db.add(workflow)
    await db.flush()
    return workflow


async def _seeded_run(db: AsyncSession) -> tuple[WorkflowRun, NodeRun]:
    """An admitted, `running` test-mode run of the one-node `debug.echo` graph,
    with its entry node's `DispatchOutbox` row ready to claim - exactly what
    `WorkflowExecutionService.start` leaves behind, built directly against the
    repository so these tests do not also depend on the facade."""
    org = await _org(db)
    graph = _echo_graph()
    workflow = await _workflow(db, org, graph)
    run = await workflow_run_repo.create_run(
        db,
        organization_id=org.id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        draft_graph_snapshot=graph.model_dump(mode="json"),
        mode=WorkflowRunMode.TEST.value,
        triggered_by="api",
        execution_principal_user_id=None,
        budget_limit=None,
        deadline_at=None,
        root_run_id=None,
        causation_run_id=None,
        visited_trigger_ids=[],
        depth=0,
        started_at=datetime.now(UTC),
    )
    node_run = await workflow_run_repo.create_node_run(
        db,
        organization_id=org.id,
        workflow_run_id=run.id,
        node_instance_id=graph.entry_node_id,
        scope_path=[],
    )
    await workflow_run_repo.create_outbox(
        db,
        organization_id=org.id,
        workflow_run_id=run.id,
        node_run_id=node_run.id,
        available_at=datetime.now(UTC),
    )
    run = await workflow_run_repo.update_run(
        db, run=run, update_data={"status": WorkflowRunStatus.RUNNING.value}
    )
    await db.commit()
    return run, node_run


async def _fresh(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_claim_commits_before_any_attempt_exists(engine: AsyncEngine, db: AsyncSession):
    """Phase 1 alone: the outbox row reads `claimed` on a second connection,
    and no `NodeAttempt` exists yet - the exact shape a crash between phase 1
    and phase 2 leaves for `workflow-reconcile`'s `list_stale_claims`."""
    run, node_run = await _seeded_run(db)

    factory = await _fresh(engine)
    async with factory() as claim_db:
        outbox = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert outbox is not None

    async with factory() as reader:
        row = (
            await reader.execute(
                select(DispatchOutbox).where(DispatchOutbox.node_run_id == node_run.id)
            )
        ).scalar_one()
        assert row.status == DispatchOutboxStatus.CLAIMED.value
        attempts = (
            (
                await reader.execute(
                    select(NodeAttempt).where(NodeAttempt.node_run_id == node_run.id)
                )
            )
            .scalars()
            .all()
        )
        assert attempts == []


async def test_begin_attempt_commits_in_flight_before_any_handler_runs(
    engine: AsyncEngine, db: AsyncSession
):
    """Phase 2 alone: the `in_flight` attempt is visible on a second
    connection - the row `workflow-reconcile`'s `list_orphaned_in_flight`
    needs to exist if the process dies before phase 4 ever runs."""
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)

    async with factory() as claim_db:
        outbox = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert outbox is not None

    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=outbox.claimed_by
        )
        await begin_db.commit()
    assert begun is not None

    async with factory() as reader:
        attempt = (
            await reader.execute(select(NodeAttempt).where(NodeAttempt.node_run_id == node_run.id))
        ).scalar_one()
        assert attempt.status == NodeAttemptStatus.IN_FLIGHT.value
        node_run_row = (
            await reader.execute(select(NodeRun).where(NodeRun.id == node_run.id))
        ).scalar_one()
        assert node_run_row.status == NodeRunStatus.RUNNING.value


async def test_settle_commits_the_result_and_the_downstream_dispatch_together(
    engine: AsyncEngine, db: AsyncSession
):
    """Phase 4: on `Completed` with no downstream node, the run's own
    terminal state (`succeeded`) and the closed-out outbox row appear
    together on a second connection - never a result with no consequence, or
    the reverse."""
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)

    async with factory() as claim_db:
        outbox = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert outbox is not None
    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=outbox.claimed_by
        )
        await begin_db.commit()
    assert begun is not None

    outcome = await dispatcher.call_handler(begun)

    async with factory() as settle_db:
        await dispatcher.settle(settle_db, begun=begun, outcome=outcome)
        await settle_db.commit()

    async with factory() as reader:
        run_row = (
            await reader.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
        ).scalar_one()
        assert run_row.status == WorkflowRunStatus.SUCCEEDED.value
        outbox_row = (
            await reader.execute(
                select(DispatchOutbox).where(DispatchOutbox.node_run_id == node_run.id)
            )
        ).scalar_one()
        assert outbox_row.status == DispatchOutboxStatus.DONE.value
        attempt = (
            await reader.execute(select(NodeAttempt).where(NodeAttempt.node_run_id == node_run.id))
        ).scalar_one()
        assert attempt.status == NodeAttemptStatus.COMPLETED.value
        assert attempt.result["output"]["echoed"] == "hi"


async def test_a_full_dispatch_tick_runs_the_one_node_graph_to_completion(
    engine: AsyncEngine, db: AsyncSession
):
    """The whole thing, in one assertion: `debug.echo`, the one node #1786
    ships with a real handler, run end to end through claim/begin/call/settle
    exactly as `workflow_dispatch_node_flow` sequences them."""
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)

    async with factory() as claim_db:
        outbox = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert outbox is not None

    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=outbox.claimed_by
        )
        await begin_db.commit()
    assert begun is not None

    outcome = await dispatcher.call_handler(begun)

    async with factory() as settle_db:
        await dispatcher.settle(settle_db, begun=begun, outcome=outcome)
        await settle_db.commit()

    async with factory() as reader:
        run_row = (
            await reader.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
        ).scalar_one()
        assert run_row.status == WorkflowRunStatus.SUCCEEDED.value
        assert run_row.ended_at is not None


async def test_a_lease_expired_before_any_attempt_is_reclaimed_exactly_once_more(
    engine: AsyncEngine, db: AsyncSession
):
    """The crash-injection scenario the design's test plan names first: the
    claim commits, the process dies before phase 2, the lease expires, and
    the reconciler's `stale_claims` finds it - reclaiming it dispatches
    exactly one more `NodeAttempt`, never a duplicate `attempt_no`."""
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)

    async with factory() as claim_db:
        await dispatcher.claim(claim_db, node_run_id=node_run.id, lease_seconds=0)
        await claim_db.commit()

    async with factory() as reconcile_db:
        pairs = await WorkflowReconcilerService(reconcile_db).stale_claims()
    assert (run.id, node_run.id) in pairs

    # The reconciler's own job is only to *find* it - `workflow_reconcile_flow`
    # re-triggers the ordinary dispatch flow for each pair, which is what
    # actually reclaims and dispatches. Reused here directly.
    async with factory() as claim_db:
        outbox = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert outbox is not None

    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=outbox.claimed_by
        )
        await begin_db.commit()
    assert begun is not None
    assert begun.attempt_no == 1

    async with factory() as reader:
        attempts = (
            (
                await reader.execute(
                    select(NodeAttempt).where(NodeAttempt.node_run_id == node_run.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(attempts) == 1


async def test_a_worker_resuming_after_its_lease_was_reclaimed_cannot_begin_a_second_attempt(
    engine: AsyncEngine, db: AsyncSession
):
    """The fencing token's whole reason to exist: a worker that claimed the

    row, then stalled past its own lease (not dead, only slow) rather than
    crashing outright, must not be able to act once somebody else has
    reclaimed the same row and is genuinely running the node - not even to
    (wrongly) treat that live attempt as an orphan of its own. Without the
    `claimed_by` re-check in `begin_attempt`, this worker would find the
    reclaiming worker's `in_flight` attempt and resolve it as orphaned out
    from under it.
    """
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)

    async with factory() as claim_db:
        stale_claim = await dispatcher.claim(claim_db, node_run_id=node_run.id, lease_seconds=0)
        await claim_db.commit()
    assert stale_claim is not None

    # The lease is already expired (`lease_seconds=0`); a second worker
    # reclaims the same row and gets past phase 2 for real.
    async with factory() as claim_db:
        fresh_claim = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert fresh_claim is not None
    assert fresh_claim.claimed_by != stale_claim.claimed_by

    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            token=fresh_claim.claimed_by,
        )
        await begin_db.commit()
    assert begun is not None

    # The original, stalled worker finally gets to phase 2 - with the token
    # `claim` minted for it back when it still owned the row.
    async with factory() as begin_db:
        stale_begun = await dispatcher.begin_attempt(
            begin_db,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            token=stale_claim.claimed_by,
        )
        await begin_db.commit()
    assert stale_begun is None

    async with factory() as reader:
        attempts = (
            (
                await reader.execute(
                    select(NodeAttempt).where(NodeAttempt.node_run_id == node_run.id)
                )
            )
            .scalars()
            .all()
        )
        # Exactly the reclaiming worker's attempt - still genuinely in
        # flight, not resolved to `uncertain` by the stale worker's call.
        assert len(attempts) == 1
        assert attempts[0].id == begun.attempt_id
        assert attempts[0].status == NodeAttemptStatus.IN_FLIGHT.value
        outbox_row = (
            await reader.execute(
                select(DispatchOutbox).where(DispatchOutbox.node_run_id == node_run.id)
            )
        ).scalar_one()
        # The live row still belongs to the reclaiming worker's claim - the
        # stale worker's failed attempt did not touch it.
        assert outbox_row.claimed_by == fresh_claim.claimed_by
        assert outbox_row.status == DispatchOutboxStatus.CLAIMED.value


async def test_an_orphaned_in_flight_idempotent_attempt_is_auto_retried_not_duplicated_blindly(
    engine: AsyncEngine, db: AsyncSession
):
    """The second named scenario: the `in_flight` attempt commits, the
    process dies before phase 4, and the lease expires. `debug.echo` is
    `idempotent`, so the reconciler queues a fresh attempt automatically -
    the orphan itself is marked `uncertain` and never claims to have
    succeeded or failed on its own."""
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)

    async with factory() as claim_db:
        first_claim = await dispatcher.claim(claim_db, node_run_id=node_run.id, lease_seconds=0)
        await claim_db.commit()
    assert first_claim is not None
    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            token=first_claim.claimed_by,
        )
        await begin_db.commit()
    assert begun is not None
    orphaned_attempt_id = begun.attempt_id
    # Never call `call_handler`/`settle` - this *is* the crash.

    async with factory() as reconcile_db:
        resolved = await WorkflowReconcilerService(reconcile_db).resolve_orphaned_attempts()
        await reconcile_db.commit()
    assert resolved == 1

    async with factory() as reader:
        orphan = (
            await reader.execute(select(NodeAttempt).where(NodeAttempt.id == orphaned_attempt_id))
        ).scalar_one()
        assert orphan.status == NodeAttemptStatus.UNCERTAIN.value
        node_run_row = (
            await reader.execute(select(NodeRun).where(NodeRun.id == node_run.id))
        ).scalar_one()
        # Still running, not needs_attention - idempotent means a fresh
        # attempt was queued automatically rather than escalated to a person.
        assert node_run_row.status == NodeRunStatus.RUNNING.value
        # Two rows now exist for this node run: the original, `done` (kept
        # for audit, never deleted) and the fresh one the retry queued.
        outbox_rows = (
            (
                await reader.execute(
                    select(DispatchOutbox).where(DispatchOutbox.node_run_id == node_run.id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.status for row in outbox_rows} == {
            DispatchOutboxStatus.DONE.value,
            DispatchOutboxStatus.PENDING.value,
        }
        # Requeued behind the same backoff a failed attempt gets, not for
        # immediate redispatch.
        retry_row = next(
            row for row in outbox_rows if row.status == DispatchOutboxStatus.PENDING.value
        )
        assert orphan.ended_at is not None and retry_row.available_at > orphan.ended_at

    async with factory() as due_db:
        await due_db.execute(
            sql_update(DispatchOutbox)
            .where(DispatchOutbox.id == retry_row.id)
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await due_db.commit()

    # And the fresh attempt actually runs the node - the retry is real, not
    # just a status flip.
    async with factory() as claim_db:
        outbox = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert outbox is not None
    async with factory() as begin_db:
        begun_again = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=outbox.claimed_by
        )
        await begin_db.commit()
    assert begun_again is not None
    assert begun_again.attempt_no == 2
    outcome = await dispatcher.call_handler(begun_again)
    async with factory() as settle_db:
        await dispatcher.settle(settle_db, begun=begun_again, outcome=outcome)
        await settle_db.commit()

    async with factory() as reader:
        run_row = (
            await reader.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
        ).scalar_one()
        assert run_row.status == WorkflowRunStatus.SUCCEEDED.value


async def test_an_orphaned_in_flight_none_guarantee_attempt_lands_in_needs_attention(
    engine: AsyncEngine, db: AsyncSession
):
    """The other half of the same scenario: a node with no safe retry
    guarantee is never auto-retried - it is left for a person, which is what
    `needs_attention` on both the node and the run means."""
    org = await _org(db)
    graph = _echo_graph()
    workflow = await _workflow(db, org, graph)
    run = await workflow_run_repo.create_run(
        db,
        organization_id=org.id,
        workflow_id=workflow.id,
        workflow_version_id=None,
        draft_graph_snapshot=graph.model_dump(mode="json"),
        mode=WorkflowRunMode.TEST.value,
        triggered_by="api",
        execution_principal_user_id=None,
        budget_limit=None,
        deadline_at=None,
        root_run_id=None,
        causation_run_id=None,
        visited_trigger_ids=[],
        depth=0,
        started_at=datetime.now(UTC),
    )
    node_run = await workflow_run_repo.create_node_run(
        db,
        organization_id=org.id,
        workflow_run_id=run.id,
        node_instance_id=graph.entry_node_id,
        scope_path=[],
    )
    await workflow_run_repo.create_outbox(
        db,
        organization_id=org.id,
        workflow_run_id=run.id,
        node_run_id=node_run.id,
        available_at=datetime.now(UTC),
    )
    await db.commit()

    factory = await _fresh(engine)
    async with factory() as claim_db:
        await dispatcher.claim(claim_db, node_run_id=node_run.id, lease_seconds=0)
        await claim_db.commit()
    async with factory() as begin_db:
        # Insert the `in_flight` attempt directly with a non-retryable
        # guarantee, standing in for a node kind #1788 does not itself ship
        # (`debug.echo` is registered `idempotent`) - the resolution policy
        # this proves is generic over `retry_guarantee`, not specific to one
        # node's own declared value.
        attempt = await workflow_run_repo.create_attempt(
            begin_db,
            organization_id=org.id,
            node_run_id=node_run.id,
            attempt_no=1,
            idempotency_key="k",
            retry_guarantee=RetryGuarantee.NONE.value,
            started_at=datetime.now(UTC),
        )
        await begin_db.commit()

    async with factory() as reconcile_db:
        resolved = await WorkflowReconcilerService(reconcile_db).resolve_orphaned_attempts()
        await reconcile_db.commit()
    assert resolved == 1

    async with factory() as reader:
        orphan = (
            await reader.execute(select(NodeAttempt).where(NodeAttempt.id == attempt.id))
        ).scalar_one()
        assert orphan.status == NodeAttemptStatus.UNCERTAIN.value
        node_run_row = (
            await reader.execute(select(NodeRun).where(NodeRun.id == node_run.id))
        ).scalar_one()
        assert node_run_row.status == NodeRunStatus.NEEDS_ATTENTION.value
        run_row = (
            await reader.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
        ).scalar_one()
        assert run_row.status == WorkflowRunStatus.NEEDS_ATTENTION.value
        # Never auto-retried: no fresh outbox row was queued.
        outbox_row = (
            await reader.execute(
                select(DispatchOutbox).where(DispatchOutbox.node_run_id == node_run.id)
            )
        ).scalar_one()
        assert outbox_row.status == DispatchOutboxStatus.DONE.value


async def _none_guarantee_orphan(
    factory: async_sessionmaker[AsyncSession], run: WorkflowRun, node_run: NodeRun
) -> tuple[DispatchOutbox, NodeAttempt]:
    """A claim whose lease is already expired, with an `in_flight` attempt of a
    node that must never run twice - the shape a worker leaves behind when it
    dies mid-handler."""
    async with factory() as claim_db:
        claim = await dispatcher.claim(claim_db, node_run_id=node_run.id, lease_seconds=0)
        await claim_db.commit()
    assert claim is not None
    async with factory() as begin_db:
        attempt = await workflow_run_repo.create_attempt(
            begin_db,
            organization_id=run.organization_id,
            node_run_id=node_run.id,
            attempt_no=1,
            idempotency_key="k",
            retry_guarantee=RetryGuarantee.NONE.value,
            started_at=datetime.now(UTC),
        )
        await begin_db.commit()
    return claim, attempt


async def _attempts(factory: async_sessionmaker[AsyncSession], node_run: NodeRun) -> list[str]:
    async with factory() as reader:
        rows = (
            await reader.execute(
                select(NodeAttempt)
                .where(NodeAttempt.node_run_id == node_run.id)
                .order_by(NodeAttempt.attempt_no)
            )
        ).scalars()
        return [row.status for row in rows]


async def test_a_reconcile_scan_overtaken_by_a_reclaim_never_runs_a_none_node_twice(
    engine: AsyncEngine, db: AsyncSession
):
    """The sweep scans an orphan, a second worker reclaims the same expired
    row before the sweep takes its locks, and only then does the sweep act.

    Resolving on the scan's word marked the reclaimer's live row `done` under
    its own token; the reclaimer's `begin_attempt` then saw its token, no
    `in_flight` attempt, and ran the `retry_guarantee="none"` node a second
    time - and that duplicate's settle moved the escalated run to `succeeded`.
    """
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)
    await _none_guarantee_orphan(factory, run, node_run)

    async with factory() as scan_db:
        scanned = await workflow_run_repo.list_orphaned_in_flight(scan_db, before=datetime.now(UTC))
    assert len(scanned) == 1

    async with factory() as claim_db:
        reclaim = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert reclaim is not None

    with patch(
        "app.services.workflow_execution.reconciler.workflow_run_repo.list_orphaned_in_flight",
        new=AsyncMock(return_value=scanned),
    ):
        async with factory() as reconcile_db:
            resolved = await WorkflowReconcilerService(reconcile_db).resolve_orphaned_attempts()
            await reconcile_db.commit()
    assert resolved == 0

    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=reclaim.claimed_by
        )
        await begin_db.commit()
    # The reclaimer found the orphan itself and escalated it - no second call.
    assert begun is None
    assert await _attempts(factory, node_run) == [NodeAttemptStatus.UNCERTAIN.value]
    async with factory() as reader:
        run_row = (
            await reader.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
        ).scalar_one()
    assert run_row.status == WorkflowRunStatus.NEEDS_ATTENTION.value


async def test_a_claim_closed_under_its_own_token_starts_no_attempt_and_settles_nothing(
    engine: AsyncEngine, db: AsyncSession
):
    """A token that still matches is not ownership once the row is closed:
    `begin_attempt` refuses without touching the row, and a settle for an
    attempt whose row was closed after it began is discarded."""
    run, node_run = await _seeded_run(db)
    factory = await _fresh(engine)
    async with factory() as claim_db:
        claim = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert claim is not None
    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=claim.claimed_by
        )
        await begin_db.commit()
    assert begun is not None
    outcome = await dispatcher.call_handler(begun)

    async with factory() as closer:
        row = (
            await closer.execute(
                select(DispatchOutbox).where(DispatchOutbox.node_run_id == node_run.id)
            )
        ).scalar_one()
        row.status = DispatchOutboxStatus.DONE.value
        await closer.commit()

    async with factory() as begin_db:
        again = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=claim.claimed_by
        )
        await begin_db.commit()
    assert again is None

    async with factory() as settle_db:
        await dispatcher.settle(settle_db, begun=begun, outcome=outcome)
        await settle_db.commit()
    assert await _attempts(factory, node_run) == [NodeAttemptStatus.IN_FLIGHT.value]
    async with factory() as reader:
        run_row = (
            await reader.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
        ).scalar_one()
    assert run_row.status == WorkflowRunStatus.RUNNING.value


@pytest.mark.parametrize(
    "settled_status", [NodeRunStatus.SUCCEEDED.value, NodeRunStatus.NEEDS_ATTENTION.value]
)
async def test_a_stray_outbox_row_never_reruns_a_node_that_already_settled(
    engine: AsyncEngine, db: AsyncSession, settled_status: str
):
    """A wake racing the node's own settle can leave a fresh `pending` row for
    a node that has since succeeded or been escalated. Claiming it must close
    it, not run the node again."""
    run, node_run = await _seeded_run(db)
    node_run = await workflow_run_repo.update_node_run(
        db, node_run=node_run, update_data={"status": settled_status}
    )
    await db.commit()
    factory = await _fresh(engine)

    async with factory() as claim_db:
        claim = await dispatcher.claim(claim_db, node_run_id=node_run.id)
        await claim_db.commit()
    assert claim is not None
    async with factory() as begin_db:
        begun = await dispatcher.begin_attempt(
            begin_db, workflow_run_id=run.id, node_run_id=node_run.id, token=claim.claimed_by
        )
        await begin_db.commit()

    assert begun is None
    assert await _attempts(factory, node_run) == []
    async with factory() as reader:
        row = (
            await reader.execute(
                select(DispatchOutbox).where(DispatchOutbox.node_run_id == node_run.id)
            )
        ).scalar_one()
    assert row.status == DispatchOutboxStatus.DONE.value
