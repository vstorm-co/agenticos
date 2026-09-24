"""The workflow-run repository against a real Postgres.

Only a real database enforces the `CHECK`s (the graph-source XOR), the
partial unique indexes (`uq_dispatch_outbox_live_node_run`,
`ix_dispatch_outbox_pending_claim`) and the plain unique constraints
(`uq_node_run_identity`, `uq_node_attempt_number`, `uq_workflow_event_seq`)
this schema is supposed to guarantee - a mock would let a second live outbox
row through silently, which is exactly the bug the index exists to make
structurally impossible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttemptStatus,
    NodeRunStatus,
    ResourceRef,
    RetryGuarantee,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo

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


async def _workflow(
    db: AsyncSession,
    org: Organization,
    *,
    owner_user_id: uuid.UUID | None = None,
    visibility: Visibility = Visibility.PRIVATE,
) -> Workflow:
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner_user_id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name="Import orders",
        status=WorkflowStatus.PUBLISHED.value,
        visibility=visibility.value,
        draft_graph={},
    )
    db.add(workflow)
    await db.flush()
    return workflow


async def _run(db: AsyncSession, org: Organization, workflow: Workflow, **overrides: object):
    defaults: dict[str, object] = {
        "organization_id": org.id,
        "workflow_id": workflow.id,
        "workflow_version_id": None,
        "draft_graph_snapshot": {"entry_node_id": str(uuid.uuid4()), "nodes": []},
        "mode": WorkflowRunMode.TEST.value,
        "triggered_by": "api",
        "execution_principal_user_id": None,
        "budget_limit": None,
        "deadline_at": None,
        "root_run_id": None,
        "causation_run_id": None,
        "visited_trigger_ids": [],
        "depth": 0,
        "started_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return await workflow_run_repo.create_run(db, **defaults)


async def _node_run(db: AsyncSession, run, **overrides: object):
    """`create_node_run` only takes identity fields - anything else
    (`status`, `waiting_reason`, `waiting_agent_run_id`, ...) is applied with
    a follow-up `update_node_run`, the same two-step shape the dispatcher
    itself uses."""
    create_fields = {"organization_id", "workflow_run_id", "node_instance_id", "scope_path"}
    defaults: dict[str, object] = {
        "organization_id": run.organization_id,
        "workflow_run_id": run.id,
        "node_instance_id": uuid.uuid4(),
        "scope_path": [],
    }
    defaults.update({key: value for key, value in overrides.items() if key in create_fields})
    node_run = await workflow_run_repo.create_node_run(db, **defaults)
    extra = {key: value for key, value in overrides.items() if key not in create_fields}
    if extra:
        node_run = await workflow_run_repo.update_node_run(db, node_run=node_run, update_data=extra)
    return node_run


class TestCreateRun:
    async def test_a_root_run_points_at_its_own_id(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        assert run.root_run_id == run.id
        assert run.causation_run_id is None

    async def test_a_caused_run_points_at_the_originating_root(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        root = await _run(db, org, workflow)
        child = await _run(
            db, org, workflow, root_run_id=root.id, causation_run_id=root.id, depth=1
        )
        assert child.root_run_id == root.id
        assert child.causation_run_id == root.id
        assert child.depth == 1

    async def test_both_graph_sources_set_is_refused(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        with pytest.raises(IntegrityError):
            await _run(
                db,
                org,
                workflow,
                workflow_version_id=uuid.uuid4(),
                draft_graph_snapshot={"entry_node_id": str(uuid.uuid4()), "nodes": []},
            )

    async def test_neither_graph_source_set_is_refused(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        with pytest.raises(IntegrityError):
            await _run(db, org, workflow, workflow_version_id=None, draft_graph_snapshot=None)


class TestGetRunIsScoped:
    async def test_get_run_is_scoped_to_the_organization(self, db: AsyncSession):
        org_a = await _org(db)
        org_b = await _org(db)
        workflow = await _workflow(db, org_a)
        run = await _run(db, org_a, workflow)
        assert await workflow_run_repo.get_run(db, run.id, organization_id=org_a.id) is not None
        assert await workflow_run_repo.get_run(db, run.id, organization_id=org_b.id) is None

    async def test_get_run_by_id_for_update_is_unscoped(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        found = await workflow_run_repo.get_run_by_id_for_update(db, run.id)
        assert found is not None
        assert found.id == run.id


class TestNodeRunIdentity:
    async def test_the_same_identity_twice_is_refused(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_instance_id = uuid.uuid4()
        await _node_run(db, run, node_instance_id=node_instance_id, scope_path=[])
        with pytest.raises(IntegrityError):
            await _node_run(db, run, node_instance_id=node_instance_id, scope_path=[])

    async def test_a_different_scope_path_is_a_different_identity(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_instance_id = uuid.uuid4()
        first = await _node_run(
            db,
            run,
            node_instance_id=node_instance_id,
            scope_path=[{"loop_node_id": "x", "index": 0}],
        )
        second = await _node_run(
            db,
            run,
            node_instance_id=node_instance_id,
            scope_path=[{"loop_node_id": "x", "index": 1}],
        )
        assert first.id != second.id

    async def test_get_by_identity_finds_the_row(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_instance_id = uuid.uuid4()
        created = await _node_run(db, run, node_instance_id=node_instance_id)
        found = await workflow_run_repo.get_node_run_by_identity(
            db, workflow_run_id=run.id, node_instance_id=node_instance_id, scope_path=[]
        )
        assert found is not None
        assert found.id == created.id


class TestNodeAttemptOrdering:
    async def test_the_same_attempt_number_twice_is_refused(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_attempt(
            db,
            organization_id=org.id,
            node_run_id=node_run.id,
            attempt_no=1,
            idempotency_key="k1",
            retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
            started_at=datetime.now(UTC),
        )
        with pytest.raises(IntegrityError):
            await workflow_run_repo.create_attempt(
                db,
                organization_id=org.id,
                node_run_id=node_run.id,
                attempt_no=1,
                idempotency_key="k2",
                retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
                started_at=datetime.now(UTC),
            )

    async def test_get_latest_attempt_finds_the_highest_number(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        for n in (1, 2, 3):
            await workflow_run_repo.create_attempt(
                db,
                organization_id=org.id,
                node_run_id=node_run.id,
                attempt_no=n,
                idempotency_key=f"k{n}",
                retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
                started_at=datetime.now(UTC),
            )
        latest = await workflow_run_repo.get_latest_attempt(db, node_run_id=node_run.id)
        assert latest is not None
        assert latest.attempt_no == 3


class TestDispatchOutboxClaim:
    async def test_claiming_a_pending_row_succeeds(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        # `func.now()` in `claim_outbox`'s own predicate is the *transaction's*
        # start time in Postgres, not wall-clock at statement time - frozen
        # before `available_at` above was even computed. A commit here starts
        # a fresh transaction, matching how `claim` always runs in its own
        # transaction in production (never the one that created the row).
        await db.commit()
        token = uuid.uuid4()
        claimed = await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=token,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        assert claimed is not None
        assert claimed.claimed_by == token
        assert claimed.status == DispatchOutboxStatus.CLAIMED.value

    async def test_claiming_an_already_claimed_row_with_a_live_lease_fails(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        await db.commit()
        await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await db.commit()
        second = await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert second is None

    async def test_a_lease_expired_claim_is_reclaimable(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        await db.commit()
        # A lease that already expired, exactly the shape a dead worker leaves.
        await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await db.commit()
        new_token = uuid.uuid4()
        reclaimed = await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=new_token,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert reclaimed is not None
        assert reclaimed.claimed_by == new_token

    async def test_a_row_not_yet_available_cannot_be_claimed(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            available_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await db.commit()
        claimed = await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        assert claimed is None

    async def test_a_second_live_outbox_row_for_the_same_node_run_is_refused(
        self, db: AsyncSession
    ):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        with pytest.raises(IntegrityError):
            await workflow_run_repo.create_outbox(
                db,
                organization_id=org.id,
                workflow_run_id=run.id,
                node_run_id=node_run.id,
            )

    async def test_a_new_outbox_row_is_allowed_once_the_old_one_is_done(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        first = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        await workflow_run_repo.mark_outbox_done(db, outbox=first)
        second = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        assert second.id != first.id

    async def test_only_due_pending_rows_are_taken_and_stamped_submitted(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        due_node_run = await _node_run(db, run)
        future_node_run = await _node_run(db, run)
        due = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=due_node_run.id,
            available_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=future_node_run.id,
            available_at=datetime.now(UTC) + timedelta(hours=1),
        )
        await db.commit()  # fresh `func.now()` for the scan below
        rows = await workflow_run_repo.take_due_for_submission(
            db, resubmit_before=datetime.now(UTC) - timedelta(minutes=2)
        )
        ids = {row.id for row in rows}
        assert due.id in ids
        assert all(row.node_run_id != future_node_run.id for row in rows)
        assert all(row.submitted_at is not None for row in rows)

    async def test_a_row_submitted_within_the_interval_is_not_taken_again(self, db: AsyncSession):
        """One submission per row per interval: a backed-up worker pool must
        not get a fresh flow run for the same row on every poll tick."""
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        row = await workflow_run_repo.create_outbox(
            db, organization_id=org.id, workflow_run_id=run.id, node_run_id=node_run.id
        )
        await db.commit()
        resubmit_before = datetime.now(UTC) - timedelta(minutes=2)

        first = await workflow_run_repo.take_due_for_submission(db, resubmit_before=resubmit_before)
        await db.commit()
        second = await workflow_run_repo.take_due_for_submission(
            db, resubmit_before=resubmit_before
        )
        await db.commit()
        # Once the interval has passed with the row still unclaimed, it is due again.
        third = await workflow_run_repo.take_due_for_submission(
            db, resubmit_before=datetime.now(UTC) + timedelta(seconds=1)
        )

        assert [taken.id for taken in first] == [row.id]
        assert second == []
        assert [taken.id for taken in third] == [row.id]

    async def test_a_row_its_creator_submits_itself_is_left_to_that_submission(
        self, db: AsyncSession
    ):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
            submitted=True,
        )
        await db.commit()

        taken = await workflow_run_repo.take_due_for_submission(
            db, resubmit_before=datetime.now(UTC) - timedelta(minutes=2)
        )

        assert taken == []


class TestEvents:
    async def test_seq_increments_per_run_and_the_run_row_tracks_it(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        first = await workflow_run_repo.append_event(
            db, run=run, kind="run_started", node_run_id=None, payload={}
        )
        second = await workflow_run_repo.append_event(
            db, run=run, kind="run_succeeded", node_run_id=None, payload={}
        )
        assert first.seq == 0
        assert second.seq == 1
        assert run.next_event_seq == 2

    async def test_list_events_since_excludes_everything_up_to_the_cursor(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        for kind in ("a", "b", "c"):
            await workflow_run_repo.append_event(
                db, run=run, kind=kind, node_run_id=None, payload={}
            )
        rows = await workflow_run_repo.list_events_since(
            db, workflow_run_id=run.id, organization_id=org.id, after_seq=0
        )
        assert [row.kind for row in rows] == ["b", "c"]

    async def test_events_are_scoped_to_the_organization(self, db: AsyncSession):
        org_a = await _org(db)
        org_b = await _org(db)
        workflow = await _workflow(db, org_a)
        run = await _run(db, org_a, workflow)
        await workflow_run_repo.append_event(
            db, run=run, kind="run_started", node_run_id=None, payload={}
        )
        rows = await workflow_run_repo.list_events_since(
            db, workflow_run_id=run.id, organization_id=org_b.id, after_seq=None
        )
        assert rows == []


async def _parked_agent_run(
    db: AsyncSession,
    org: Organization,
    *,
    slug: str,
    status: str = RunStatus.AWAITING_APPROVAL.value,
) -> tuple[Agent, AgentRun]:
    agent = Agent(id=uuid.uuid4(), organization_id=org.id, slug=slug, name="Clerk", draft_spec={})
    db.add(agent)
    await db.flush()
    agent_run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        surface="api",
        status=status,
        started_at=datetime.now(UTC),
    )
    db.add(agent_run)
    await db.flush()
    return agent, agent_run


class TestStaleApprovalWaits:
    """`ApprovalService.decide` only ever writes `ToolApproval` - never

    `agent_runs.status`, which stays `awaiting_approval` until something
    actually calls `AgentRunnerService.resume` - so "the decision already
    landed" has to be read off `tool_approvals.status`, not off the agent
    run. See the comment on `list_stale_approval_waits` itself.
    """

    async def test_finds_a_node_run_whose_blocking_approval_was_decided(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        agent, agent_run = await _parked_agent_run(db, org, slug="clerk")
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=org.id,
                run_id=agent_run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status=ApprovalStatus.APPROVED.value,
            )
        )
        await db.flush()
        node_run = await _node_run(
            db,
            run,
            status=NodeRunStatus.WAITING.value,
            waiting_reason="approval",
            waiting_agent_run_id=agent_run.id,
        )
        found = await workflow_run_repo.list_stale_approval_waits(db)
        assert node_run.id in {row.id for row in found}

    async def test_a_node_run_whose_owning_workflow_run_is_terminal_is_not_found(
        self, db: AsyncSession
    ):
        """`cancel()` leaves a waiting `NodeRun` and its linked `agent_runs`

        row exactly as they were (a documented gap -
        `WorkflowExecutionService.cancel`), so the two other guards stay
        true forever once the approval is decided. Without excluding a
        terminal owning run here, `wake_stale_approval_decisions` would
        re-insert an outbox row on every sweep for `begin_attempt` to
        immediately close again as soon as it saw the cancelled run -
        forever, not once.
        """
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        run = await workflow_run_repo.update_run(
            db, run=run, update_data={"status": WorkflowRunStatus.CANCELLED.value}
        )
        agent, agent_run = await _parked_agent_run(db, org, slug="clerk-cancelled-run")
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=org.id,
                run_id=agent_run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status=ApprovalStatus.APPROVED.value,
            )
        )
        await db.flush()
        node_run = await _node_run(
            db,
            run,
            status=NodeRunStatus.WAITING.value,
            waiting_reason="approval",
            waiting_agent_run_id=agent_run.id,
        )
        found = await workflow_run_repo.list_stale_approval_waits(db)
        assert node_run.id not in {row.id for row in found}

    @pytest.mark.security
    async def test_a_node_run_whose_approval_is_still_pending_is_not_found(self, db: AsyncSession):
        """The reconciler backstop must not race ahead of the human: a

        `NodeRun` parked on a call nobody has decided yet is not "the wake
        was lost", it is "there is nothing to wake yet."
        """
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        agent, agent_run = await _parked_agent_run(db, org, slug="clerk-pending")
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=org.id,
                run_id=agent_run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status=ApprovalStatus.PENDING.value,
            )
        )
        await db.flush()
        node_run = await _node_run(
            db,
            run,
            status=NodeRunStatus.WAITING.value,
            waiting_reason="approval",
            waiting_agent_run_id=agent_run.id,
        )
        found = await workflow_run_repo.list_stale_approval_waits(db)
        assert node_run.id not in {row.id for row in found}

    @pytest.mark.parametrize(
        "agent_status,woken",
        [
            # Ended without ever being resumed - an expired approval cancels it.
            (RunStatus.CANCELLED.value, True),
            (RunStatus.FAILED.value, True),
            # Somebody is resuming it right now; the node is found once it ends.
            (RunStatus.RUNNING.value, False),
        ],
    )
    async def test_an_agent_run_that_moved_on_wakes_its_node_once_it_is_not_running(
        self, db: AsyncSession, agent_status: str, woken: bool
    ):
        """A node parked on an agent run that ended unresumed must wake, so its
        handler sees that outcome and fails the node - left alone it would wait
        for ever on a run nothing will resume."""
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        agent, agent_run = await _parked_agent_run(
            db, org, slug=f"clerk-{agent_status}", status=agent_status
        )
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=org.id,
                run_id=agent_run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status=ApprovalStatus.EXPIRED.value,
            )
        )
        await db.flush()
        node_run = await _node_run(
            db,
            run,
            status=NodeRunStatus.WAITING.value,
            waiting_reason="approval",
            waiting_agent_run_id=agent_run.id,
        )
        found = await workflow_run_repo.list_stale_approval_waits(db)
        assert (node_run.id in {row.id for row in found}) is woken

    async def test_a_node_run_already_covered_by_a_live_outbox_row_is_excluded(
        self, db: AsyncSession
    ):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        agent, agent_run = await _parked_agent_run(db, org, slug="clerk2")
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=org.id,
                run_id=agent_run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status=ApprovalStatus.APPROVED.value,
            )
        )
        await db.flush()
        node_run = await _node_run(
            db,
            run,
            status=NodeRunStatus.WAITING.value,
            waiting_reason="approval",
            waiting_agent_run_id=agent_run.id,
        )
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        found = await workflow_run_repo.list_stale_approval_waits(db)
        assert node_run.id not in {row.id for row in found}


class TestOrphanedInFlightAttempts:
    async def test_finds_an_in_flight_attempt_whose_claimed_lease_expired(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        await db.commit()
        await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await db.commit()
        attempt = await workflow_run_repo.create_attempt(
            db,
            organization_id=org.id,
            node_run_id=node_run.id,
            attempt_no=1,
            idempotency_key="k",
            retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
            started_at=datetime.now(UTC),
        )
        found = await workflow_run_repo.list_orphaned_in_flight(
            db, before=datetime.now(UTC), closed_before=datetime.now(UTC) - timedelta(minutes=2)
        )
        assert attempt.id in {row.id for row in found}

    async def test_orphans_come_back_in_the_order_their_runs_are_locked(self, db: AsyncSession):
        """The sweep locks each orphan's run in scan order and holds every lock
        to its commit; two sweeps agree on the order only if the scan does."""
        org = await _org(db)
        workflow = await _workflow(db, org)
        node_runs = []
        for _ in range(3):
            run = await _run(db, org, workflow)
            node_run = await _node_run(db, run)
            await workflow_run_repo.create_outbox(
                db,
                organization_id=org.id,
                workflow_run_id=run.id,
                node_run_id=node_run.id,
            )
            node_runs.append(node_run)
        await db.commit()
        for node_run in node_runs:
            await workflow_run_repo.claim_outbox(
                db,
                node_run_id=node_run.id,
                token=uuid.uuid4(),
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
            await workflow_run_repo.create_attempt(
                db,
                organization_id=org.id,
                node_run_id=node_run.id,
                attempt_no=1,
                idempotency_key="k",
                retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
                started_at=datetime.now(UTC),
            )

        found = await workflow_run_repo.list_orphaned_in_flight(
            db, before=datetime.now(UTC), closed_before=datetime.now(UTC) - timedelta(minutes=2)
        )

        run_of = {node_run.id: node_run.workflow_run_id for node_run in node_runs}
        order = [run_of[attempt.node_run_id] for attempt in found]
        assert order == sorted(run_of.values())

    async def test_a_completed_attempt_is_never_orphaned(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        await db.commit()
        await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await db.commit()
        attempt = await workflow_run_repo.create_attempt(
            db,
            organization_id=org.id,
            node_run_id=node_run.id,
            attempt_no=1,
            idempotency_key="k",
            retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
            started_at=datetime.now(UTC),
        )
        await workflow_run_repo.settle_attempt(
            db,
            attempt=attempt,
            status=NodeAttemptStatus.COMPLETED.value,
            result={"status": "completed"},
            cost=Decimal("0"),
            cost_is_partial=False,
            ended_at=datetime.now(UTC),
        )
        found = await workflow_run_repo.list_orphaned_in_flight(
            db, before=datetime.now(UTC), closed_before=datetime.now(UTC) - timedelta(minutes=2)
        )
        assert attempt.id not in {row.id for row in found}


class TestStaleClaims:
    async def test_a_claim_stranded_before_any_attempt_is_found(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        outbox = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        await db.commit()
        await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await db.commit()
        found = await workflow_run_repo.take_stale_claims_for_resubmission(
            db, before=datetime.now(UTC), resubmit_before=datetime.now(UTC) - timedelta(minutes=2)
        )
        assert outbox.id in {row.id for row in found}
        await db.commit()
        again = await workflow_run_repo.take_stale_claims_for_resubmission(
            db, before=datetime.now(UTC), resubmit_before=datetime.now(UTC) - timedelta(minutes=2)
        )
        # Stamped when it was taken, so the next sweep leaves it to that submission.
        assert again == []

    async def test_a_claim_with_an_in_flight_attempt_is_not_a_stale_claim(self, db: AsyncSession):
        # It is an orphaned *attempt* instead - `list_orphaned_in_flight`'s job.
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        outbox = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        await db.commit()
        await workflow_run_repo.claim_outbox(
            db,
            node_run_id=node_run.id,
            token=uuid.uuid4(),
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        await db.commit()
        await workflow_run_repo.create_attempt(
            db,
            organization_id=org.id,
            node_run_id=node_run.id,
            attempt_no=1,
            idempotency_key="k",
            retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
            started_at=datetime.now(UTC),
        )
        found = await workflow_run_repo.take_stale_claims_for_resubmission(
            db, before=datetime.now(UTC), resubmit_before=datetime.now(UTC)
        )
        assert outbox.id not in {row.id for row in found}


class TestReprs:
    async def test_every_model_repr_names_its_identity(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        node_run = await _node_run(db, run)
        attempt = await workflow_run_repo.create_attempt(
            db,
            organization_id=org.id,
            node_run_id=node_run.id,
            attempt_no=1,
            idempotency_key="k",
            retry_guarantee=RetryGuarantee.IDEMPOTENT.value,
            started_at=datetime.now(UTC),
        )
        outbox = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=node_run.id,
        )
        event = await workflow_run_repo.append_event(
            db, run=run, kind="run_started", node_run_id=None, payload={}
        )
        resource_ref = await workflow_run_repo.create_resource_ref(
            db, organization_id=org.id, workflow_run_id=run.id, kind="file", ref={"kind": "file"}
        )
        assert str(run.id) in repr(run)
        assert str(node_run.id) in repr(node_run)
        assert str(attempt.id) in repr(attempt)
        assert str(outbox.id) in repr(outbox)
        # `WorkflowEvent.__repr__` names the run and `seq`, not its own id -
        # `seq` is the meaningful identity for an append-only event stream.
        assert str(event.seq) in repr(event)
        assert str(resource_ref.id) in repr(resource_ref)


class TestGetRunForUpdate:
    async def test_locks_and_returns_the_row(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        found = await workflow_run_repo.get_run_for_update(db, run.id, organization_id=org.id)
        assert found is not None
        assert found.id == run.id

    async def test_is_scoped_to_the_organization(self, db: AsyncSession):
        org_a = await _org(db)
        org_b = await _org(db)
        workflow = await _workflow(db, org_a)
        run = await _run(db, org_a, workflow)
        assert (
            await workflow_run_repo.get_run_for_update(db, run.id, organization_id=org_b.id) is None
        )


class TestListRuns:
    async def test_narrowed_to_one_workflow(self, db: AsyncSession):
        org = await _org(db)
        workflow_a = await _workflow(db, org)
        workflow_b = await _workflow(db, org)
        run_a = await _run(db, org, workflow_a)
        await _run(db, org, workflow_b)
        items, total = await workflow_run_repo.list_runs(
            db, organization_id=org.id, workflow_id=workflow_a.id
        )
        assert total == 1
        assert [item.id for item in items] == [run_a.id]

    async def test_a_user_sees_runs_of_their_own_org_visible_and_shared_workflows(
        self, db: AsyncSession
    ):
        """The same three ways in as the workflow listing - owned, visible to
        the organization, shared - and another member's private workflow is
        not one of them."""
        org = await _org(db)
        me, colleague = uuid.uuid4(), uuid.uuid4()
        for user_id in (me, colleague):
            db.add(User(id=user_id, email=f"{user_id.hex}@example.com", hashed_password="x"))
        await db.flush()
        mine = await _workflow(db, org, owner_user_id=me)
        org_wide = await _workflow(db, org, owner_user_id=colleague, visibility=Visibility.ORG)
        shared = await _workflow(db, org, owner_user_id=colleague)
        private = await _workflow(db, org, owner_user_id=colleague)
        runs = {wf.id: await _run(db, org, wf) for wf in (mine, org_wide, shared, private)}

        items, total = await workflow_run_repo.list_runs(
            db, organization_id=org.id, visible_to_user_id=me, shared_workflow_ids=[shared.id]
        )

        assert total == 3
        assert {item.id for item in items} == {
            runs[mine.id].id,
            runs[org_wide.id].id,
            runs[shared.id].id,
        }

    async def test_no_user_to_narrow_by_sees_everything(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        await _run(db, org, workflow)
        await _run(db, org, workflow)
        _items, total = await workflow_run_repo.list_runs(db, organization_id=org.id)
        assert total == 2


class TestFindNodeRunWaitingOnAgentRun:
    async def test_finds_the_node_run_parked_on_this_agent_run(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        agent = Agent(
            id=uuid.uuid4(), organization_id=org.id, slug="find-clerk", name="Clerk", draft_spec={}
        )
        db.add(agent)
        await db.flush()
        agent_run = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            surface="api",
            status=RunStatus.AWAITING_APPROVAL.value,
            started_at=datetime.now(UTC),
        )
        db.add(agent_run)
        await db.flush()
        node_run = await _node_run(
            db, run, status=NodeRunStatus.WAITING.value, waiting_agent_run_id=agent_run.id
        )
        found = await workflow_run_repo.find_node_run_waiting_on_agent_run(
            db, agent_run.id, organization_id=org.id
        )
        assert found is not None
        assert found.id == node_run.id

    async def test_is_scoped_to_the_organization(self, db: AsyncSession):
        org_a = await _org(db)
        org_b = await _org(db)
        workflow = await _workflow(db, org_a)
        run = await _run(db, org_a, workflow)
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            slug="find-clerk-2",
            name="Clerk",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        agent_run = AgentRun(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            agent_id=agent.id,
            surface="api",
            status=RunStatus.AWAITING_APPROVAL.value,
            started_at=datetime.now(UTC),
        )
        db.add(agent_run)
        await db.flush()
        await _node_run(
            db, run, status=NodeRunStatus.WAITING.value, waiting_agent_run_id=agent_run.id
        )
        found = await workflow_run_repo.find_node_run_waiting_on_agent_run(
            db, agent_run.id, organization_id=org_b.id
        )
        assert found is None


class TestCancelLiveOutboxForRun:
    async def test_cancels_pending_and_claimed_rows_but_leaves_done_ones(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        pending_node_run = await _node_run(db, run)
        done_node_run = await _node_run(db, run)
        pending = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=pending_node_run.id,
        )
        done = await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=done_node_run.id,
        )
        await workflow_run_repo.mark_outbox_done(db, outbox=done)

        cancelled_ids = await workflow_run_repo.cancel_live_outbox_for_run(
            db, workflow_run_id=run.id
        )

        assert pending.id in cancelled_ids
        assert done.id not in cancelled_ids
        statuses = dict(
            (
                await db.execute(
                    select(DispatchOutbox.id, DispatchOutbox.status).where(
                        DispatchOutbox.workflow_run_id == run.id
                    )
                )
            ).all()
        )
        assert statuses == {
            pending.id: DispatchOutboxStatus.CANCELLED.value,
            done.id: DispatchOutboxStatus.DONE.value,
        }


class TestResourceRefs:
    async def test_each_resolved_reference_is_recorded_against_its_run(self, db: AsyncSession):
        org = await _org(db)
        workflow = await _workflow(db, org)
        run = await _run(db, org, workflow)
        first = await workflow_run_repo.create_resource_ref(
            db, organization_id=org.id, workflow_run_id=run.id, kind="file", ref={"kind": "file"}
        )
        second = await workflow_run_repo.create_resource_ref(
            db, organization_id=org.id, workflow_run_id=run.id, kind="table", ref={"kind": "table"}
        )
        rows = (
            (await db.execute(select(ResourceRef).where(ResourceRef.workflow_run_id == run.id)))
            .scalars()
            .all()
        )
        assert {(row.id, row.kind) for row in rows} == {(first.id, "file"), (second.id, "table")}
