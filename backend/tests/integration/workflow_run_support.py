"""Seeding a workflow run and driving it to the end, against a real Postgres.

The node suites (#1789 onward) test what a graph *does*, not one dispatch
phase: they seed a run the way `WorkflowExecutionService.start` leaves one,
then tick every node whose outbox row is waiting - `claim`, `begin_attempt`,
`call_handler`, `settle`, one committed transaction each, the order
`workflow_dispatch_node_flow` runs them in - until nothing is left to claim.
`tests/integration/test_workflow_run_dispatch.py` is where the phases
themselves are tested one at a time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeRun,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import dispatcher
from app.workflows.graph.model import WorkflowGraph


@dataclass
class SeededRun:
    run: WorkflowRun
    graph: WorkflowGraph
    principal: User
    org: Organization
    factory: async_sessionmaker[AsyncSession]

    @property
    def ctx(self) -> AuthContext:
        return AuthContext(user_id=self.principal.id, organization_id=self.org.id, role="owner")


async def seed_member(db: AsyncSession, *, role: str = "owner") -> tuple[User, Organization]:
    """An active user who is a member of a fresh organization."""
    principal = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(principal)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=principal.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=principal.id, role=role)
    )
    await db.flush()
    return principal, org


async def seed_run(
    engine: AsyncEngine,
    graph: WorkflowGraph,
    *,
    run_input: dict[str, Any] | None = None,
    triggered_by: str = "api",
    member: tuple[User, Organization] | None = None,
) -> SeededRun:
    """A `running` test-mode run of `graph` with its entry node queued.

    `member` reuses a principal and organization the test already seeded -
    for a graph that reads resources (a collection, an agent) the test made
    for that organization first.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        principal, org = member if member is not None else await seed_member(db)
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=org.id,
            owner_user_id=principal.id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Graph",
            status=WorkflowStatus.PUBLISHED.value,
            visibility=Visibility.PRIVATE.value,
            draft_graph=graph.model_dump(mode="json"),
        )
        db.add(workflow)
        await db.flush()
        run = await workflow_run_repo.create_run(
            db,
            organization_id=org.id,
            workflow_id=workflow.id,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
            mode=WorkflowRunMode.TEST.value,
            triggered_by=triggered_by,
            execution_principal_user_id=principal.id,
            budget_limit=None,
            node_count=len(graph.nodes),
            deadline_at=None,
            root_run_id=None,
            causation_run_id=None,
            visited_trigger_ids=[],
            depth=0,
            started_at=datetime.now(UTC),
            run_input=run_input,
        )
        entry = await workflow_run_repo.create_node_run(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_instance_id=graph.entry_node_id,
            scope_path=[],
        )
        await workflow_run_repo.create_outbox(
            db, organization_id=org.id, workflow_run_id=run.id, node_run_id=entry.id
        )
        run = await workflow_run_repo.update_run(
            db, run=run, update_data={"status": WorkflowRunStatus.RUNNING.value}
        )
        await db.commit()
    return SeededRun(run=run, graph=graph, principal=principal, org=org, factory=factory)


async def tick(seeded: SeededRun, node_run_id: uuid.UUID) -> None:
    """One dispatch tick for `node_run_id`, one committed transaction per phase."""
    async with seeded.factory() as db:
        claim = await dispatcher.claim(db, node_run_id=node_run_id)
        await db.commit()
    if claim is None or claim.claimed_by is None:
        return
    async with seeded.factory() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=seeded.run.id, node_run_id=node_run_id, token=claim.claimed_by
        )
        await db.commit()
    if begun is None:
        return
    outcome = await dispatcher.call_handler(begun)
    async with seeded.factory() as db:
        await dispatcher.settle(db, begun=begun, outcome=outcome)
        await db.commit()


async def drive(seeded: SeededRun, *, max_ticks: int = 200) -> WorkflowRun:
    """Tick every waiting node until none is left, and return the run as it ended.

    Raises:
        AssertionError: More than `max_ticks` ticks - a graph that never settles.
    """
    for _ in range(max_ticks):
        async with seeded.factory() as db:
            waiting = (
                await db.execute(
                    select(DispatchOutbox.node_run_id)
                    .where(
                        DispatchOutbox.workflow_run_id == seeded.run.id,
                        DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
                    )
                    .order_by(DispatchOutbox.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
        if waiting is None:
            return await run_row(seeded)
        await tick(seeded, waiting)
    raise AssertionError(f"The run did not settle within {max_ticks} ticks")


async def run_row(seeded: SeededRun) -> WorkflowRun:
    async with seeded.factory() as db:
        return (
            await db.execute(select(WorkflowRun).where(WorkflowRun.id == seeded.run.id))
        ).scalar_one()


async def node_statuses(seeded: SeededRun) -> dict[uuid.UUID, str]:
    """Each node instance's `NodeRun` status, at the top-level scope."""
    async with seeded.factory() as db:
        rows = (
            await db.execute(
                select(NodeRun).where(
                    NodeRun.workflow_run_id == seeded.run.id, NodeRun.scope_path == []
                )
            )
        ).scalars()
        return {row.node_instance_id: row.status for row in rows}
