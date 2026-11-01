"""Seeding a workflow run and driving it to the end, against a real Postgres.

The node suites (#1789 onward) test what a graph *does*, not one dispatch
phase: they seed a run the way `WorkflowExecutionService.start` leaves one,
then tick every node whose outbox row is waiting - `claim`, `begin_attempt`,
`call_handler`, `settle`, one committed transaction each, the order
`workflow_tasks.dispatch_node` runs them in - until nothing is left to claim.
`tests/integration/test_workflow_run_dispatch.py` is where the phases
themselves are tested one at a time, and `run_next_job` / `worker_running` stand a
worker in for the job queue: they claim `workflow-dispatch-node` jobs and run the
production handlers.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.factory import BuiltAgent, build_agent
from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.background_job import BackgroundJob
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
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
from app.repositories import background_job as job_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.agent_registry import AgentRegistryService
from app.services.workflow_execution import dispatcher
from app.worker import handlers
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
            # As `WorkflowExecutionService._admit` stores it for a root.
            public_origin=triggered_by in dispatcher.PUBLIC_TRIGGERS,
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


async def queued_dispatches(
    factory: async_sessionmaker[AsyncSession], *, workflow_run_id: uuid.UUID | None = None
) -> list[BackgroundJob]:
    """The `workflow-dispatch-node` jobs in the queue, oldest first, of one run if named."""
    async with factory() as db:
        jobs = (
            (
                await db.execute(
                    select(BackgroundJob)
                    .where(BackgroundJob.kind == "workflow-dispatch-node")
                    .order_by(BackgroundJob.created_at, BackgroundJob.id)
                )
            )
            .scalars()
            .all()
        )
    return [
        job
        for job in jobs
        if workflow_run_id is None or job.payload["workflow_run_id"] == str(workflow_run_id)
    ]


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


async def start_attempt(seeded: SeededRun, node_run_id: uuid.UUID) -> dispatcher.BegunAttempt:
    """Claim a step and commit its `in_flight` attempt, leaving the handler uncalled."""
    async with seeded.factory() as db:
        claim = await dispatcher.claim(db, node_run_id=node_run_id)
        await db.commit()
    assert claim is not None and claim.claimed_by is not None
    async with seeded.factory() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=seeded.run.id, node_run_id=node_run_id, token=claim.claimed_by
        )
        await db.commit()
    assert begun is not None
    return begun


async def begin(
    seeded: SeededRun, node_run_id: uuid.UUID
) -> tuple[dispatcher.BegunAttempt, dispatcher.HandlerOutcome]:
    """The first three phases of a tick - claim, begin, call - leaving `settle` to the test.

    For a test that needs two steps of one run in flight at once.
    """
    begun = await start_attempt(seeded, node_run_id)
    return begun, await dispatcher.call_handler(begun)


async def settle(
    seeded: SeededRun, begun: dispatcher.BegunAttempt, outcome: dispatcher.HandlerOutcome
) -> None:
    """Settle one attempt `begin` left in flight, in a transaction of its own."""
    async with seeded.factory() as db:
        await dispatcher.settle(db, begun=begun, outcome=outcome)
        await db.commit()


async def drive(
    seeded: SeededRun, *, max_ticks: int = 200, first: uuid.UUID | None = None
) -> WorkflowRun:
    """Tick every node that is due until none is left, and return the run as it stands.

    A row held back for a retry's backoff is not due, so a run waiting to retry
    comes back `waiting_retry` rather than being ticked past its own schedule.

    Sibling legs are enqueued in one transaction, so they carry the same `created_at`
    and nothing says which is ticked first. A test whose outcome depends on that
    order names the node that must go first as `first`.

    Raises:
        AssertionError: More than `max_ticks` ticks - a graph that never settles.
    """
    priority = case((NodeRun.node_instance_id == first, 0), else_=1) if first is not None else None
    for _ in range(max_ticks):
        async with seeded.factory() as db:
            due = (
                select(DispatchOutbox.node_run_id)
                .join(NodeRun, NodeRun.id == DispatchOutbox.node_run_id)
                .where(
                    DispatchOutbox.workflow_run_id == seeded.run.id,
                    DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
                    DispatchOutbox.available_at <= func.now(),
                )
            )
            if priority is not None:
                due = due.order_by(priority)
            waiting = (
                await db.execute(due.order_by(DispatchOutbox.created_at).limit(1))
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


async def seed_agent(
    factory: async_sessionmaker[AsyncSession], principal: User, org: Organization
) -> dict[str, str]:
    """A published agent of `org`, on a model profile with a stand-in key, as an
    `agent.run` step's config pins it. Pair it with `run_people`, whose model
    answers in-process."""
    ctx = AuthContext(user_id=principal.id, organization_id=org.id, role="owner")
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key-0000"), scope=VaultScope.organization(org.id)
    )
    async with factory() as db:
        secret = OrganizationSecret(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=f"Key {uuid.uuid4().hex[:6]}",
            purpose="openai",
            visibility="org",
            kind=SecretKind.API_KEY.value,
            sealed_secret=sealed.ciphertext,
            hint=sealed.hint,
        )
        db.add(secret)
        await db.flush()
        profile = ModelProfile(
            id=uuid.uuid4(),
            organization_id=org.id,
            label=f"Default {uuid.uuid4().hex[:6]}",
            provider="openai",
            model="gpt-4.1",
            secret_id=secret.id,
        )
        db.add(profile)
        await db.flush()
        registry = AgentRegistryService(db)
        agent = await registry.create(
            ctx,
            AgentSpec(
                name=f"Agent {uuid.uuid4().hex[:6]}",
                instructions="You answer briefly.",
                model_profile_id=profile.id,
            ),
        )
        version = await registry.publish(ctx, agent.id)
        await db.commit()
    return {"agent_id": str(agent.id), "version_id": str(version.id)}


@contextmanager
def run_people() -> Iterator[list[uuid.UUID | None]]:
    """The run person of every agent an `agent.run` step builds, in order.

    The model answers in-process, so a step runs to its end without a provider.
    """

    async def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Done.")])

    seen: list[uuid.UUID | None] = []

    def recording(*args: Any, **kwargs: Any) -> BuiltAgent:
        seen.append(kwargs["run_person"])
        return build_agent(*args, **kwargs)

    with (
        patch("app.agents.model_resolver.build_model", lambda *_args: FunctionModel(respond)),
        patch("app.services.agent_runner.build_agent", recording),
    ):
        yield seen


async def run_next_job(
    factory: async_sessionmaker[AsyncSession], *, pool: str = "workflow"
) -> bool:
    """Claim the next due job of `pool` the way a worker does, run its production
    handler and settle it. `False` when nothing is due."""
    async with factory() as db:
        job = await job_repo.claim(
            db, pool=pool, worker_id="test-worker", lease=timedelta(minutes=1)
        )
        await db.commit()
    if job is None:
        return False
    try:
        result = await handlers.production()[job.kind].execute(job.payload)
    except Exception as exc:
        async with factory() as db:
            await job_repo.fail(
                db, job.id, fence=job.attempts, error=repr(exc), retry_in=timedelta(0)
            )
            await db.commit()
        raise
    async with factory() as db:
        await job_repo.complete(db, job.id, fence=job.attempts, result=result)
        await db.commit()
    return True


async def run_jobs(factory: async_sessionmaker[AsyncSession], *, limit: int = 200) -> int:
    """Run every due job, successors included, until none is due; returns how many ran."""
    ran = 0
    while await run_next_job(factory):
        ran += 1
        assert ran <= limit, "the queue did not drain"
    return ran


@asynccontextmanager
async def worker_running(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """A worker claiming and running jobs in the background, for a test that waits on a run."""

    async def loop() -> None:
        while True:
            try:
                ran = await run_next_job(factory)
            except Exception:
                # The job is settled failed; the test sees it in the run's status.
                ran = True
            if not ran:
                await asyncio.sleep(0.05)

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
