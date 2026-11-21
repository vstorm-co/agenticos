"""Durable source admission and tenant ownership against PostgreSQL."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import anyio
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Scope
from app.db.locks import LockScope, hold_subject
from app.db.models.background_job import BackgroundJob
from app.db.models.event_source import (
    EventDelivery,
    EventDispatch,
    EventSource,
    EventSourceCredential,
    EventSubscription,
)
from app.db.models.organization import Organization
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.schemas.agent_trigger import TriggerCreate
from app.schemas.event_source import (
    EventSourceCreate,
    EventSourceTarget,
    SourceAuth,
    SourceCredentials,
)
from app.schemas.workflow import WorkflowPublish, WorkflowSettings
from app.services import event_sources as module
from app.services import rate_limit
from app.services.agent_trigger import AgentTriggerService
from app.services.event_source_samples import EventSourceSampleService
from app.services.event_sources import EventSourceService
from app.services.workflow_registry import WorkflowRegistryService
from app.worker.executors import Succeeded, run_handler
from app.worker.jobs import DISPATCH_SOURCE_EVENT, DispatchSourceEvent
from app.worker.registry import Handler, by_kind
from app.worker.tasks import event_source_tasks
from app.workflows.graph.model import WorkflowGraph
from tests.integration.test_routine_sources import world
from tests.integration.test_workflow_exposures import (
    _ctx,
    _graph,
    _member,
    _org,
    _publish,
    _user,
    _workflow,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def source_world(db, monkeypatch):
    user = await _user(db)
    org = await _org(db, owner=user)
    ctx = _ctx(user, org)
    source = await EventSourceService(db).create(
        ctx,
        EventSourceCreate(
            name="Events",
            auth=SourceAuth(method="api_key", header_name="x-api-key", signature_prefix=""),
            credentials=SourceCredentials(secret=SecretStr("source-test-key")),
        ),
    )
    monkeypatch.setattr(
        rate_limit,
        "workflow_webhook_allowed",
        AsyncMock(return_value=rate_limit.Decision(allowed=True, retry_after_seconds=0)),
    )
    return ctx, org, user, source


async def _subscribed(db, world):
    ctx, org, user, source = world
    workflow = await _workflow(db, org=org, owner=user)
    published = await _publish(
        db, ctx, workflow, _graph("trigger.webhook", {"source_id": str(source.id)})
    )
    return workflow, published


async def _receive(db, source_id, event_id="event-1"):
    headers = {"x-api-key": "source-test-key"}
    if event_id is not None:
        headers["x-delivery-id"] = event_id
    return await EventSourceService(db).receive(
        source_id, body=b'{"issue":{"title":"Help"},"values":[false,0,null]}', headers=headers
    )


async def _count(db, model):
    return await db.scalar(select(func.count()).select_from(model))


@pytest.mark.security
async def test_sample_listener_requires_target_management_even_with_source_use(
    db: AsyncSession, source_world
) -> None:
    ctx, org, owner, _ = source_world
    source = await EventSourceService(db).create(
        ctx, EventSourceCreate(name="Shared", visibility="org")
    )
    workflow = await _workflow(db, org=org, owner=owner)
    target = EventSourceTarget(kind="workflow", id=workflow.id)
    user = await _user(db)
    await _member(db, org=org, user=user, role="operator")
    operator = _ctx(user, org, role="operator")
    await EventSourceService(db).require_use(operator, source.id)

    cache = AsyncMock(spec=RedisClient)
    samples = EventSourceSampleService(db, cache)
    with pytest.raises(AuthorizationError):
        await samples.listen(operator, source.id, target)
    cache.set.assert_not_awaited()

    grant = ResourceGrant(
        organization_id=org.id,
        resource_type="workflow",
        resource_id=workflow.id,
        subject_user_id=user.id,
        level="edit",
    )
    db.add(grant)
    await db.flush()
    listener = await samples.listen(operator, source.id, target)
    cache.get.return_value = target.model_dump_json()
    await db.delete(grant)
    await db.flush()
    with pytest.raises(AuthorizationError):
        await samples.caught(operator, source.id, listener.listener_id)
    cache.get.assert_awaited_once()


@pytest.mark.security
async def test_source_list_pages_only_visible_sources_and_reports_granted_permissions(
    db: AsyncSession, source_world
) -> None:
    ctx, org, owner, hidden = source_world
    viewer = await _user(db)
    await _member(db, org=org, user=viewer, role="viewer")
    service = EventSourceService(db)
    shared = await service.create(ctx, EventSourceCreate(name="A grant"))
    published = await service.create(
        ctx, EventSourceCreate(name="B organization", visibility="org")
    )
    foreign = await _org(db, owner=owner)
    await service.create(
        _ctx(owner, foreign), EventSourceCreate(name="C foreign", visibility="org")
    )
    db.add(
        ResourceGrant(
            organization_id=org.id,
            resource_type="event_source",
            resource_id=shared.id,
            subject_user_id=viewer.id,
            level="use",
        )
    )
    await db.flush()

    reader = _ctx(viewer, org, role="viewer")
    first = await service.list(reader, limit=1)
    second = await service.list(reader, skip=1, limit=1)
    assert first.total == second.total == 2
    assert [item.id for item in first.items + second.items] == [shared.id, published.id]
    assert first.items[0].can_use and not first.items[0].can_edit
    assert all(item.id != hidden.id for item in first.items + second.items)
    assert (await service.list(ctx)).total == 3
    owned, total = await module.repo.list_sources(
        db,
        organization_id=org.id,
        user_id=viewer.id,
        scope=Scope.OWN,
        shared_ids=[shared.id],
        skip=0,
        limit=50,
    )
    assert total == 1 and [item.id for item in owned] == [shared.id]
    granted, total = await module.repo.list_sources(
        db,
        organization_id=org.id,
        user_id=owner.id,
        scope=Scope.NONE,
        shared_ids=[shared.id],
        skip=0,
        limit=50,
    )
    assert total == 1 and [item.id for item in granted] == [shared.id]


async def test_delivery_and_each_subscriber_survive_dispatch_restart_without_duplicate_runs(
    db, engine, source_world, monkeypatch
):
    ctx, _, _, source = source_world
    first_workflow, first = await _subscribed(db, source_world)
    second_workflow, second = await _subscribed(db, source_world)
    _, receipt, accepted = await _receive(db, source.id)
    _, _, duplicate = await _receive(db, source.id)
    assert accepted and not duplicate
    assert await _count(db, EventDelivery) == 1
    assert await _count(db, EventDispatch) == 2
    assert (
        await db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == "dispatch-source-event")
        )
        == 2
    )
    dispatches = list(await db.scalars(select(EventDispatch)))
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def restarted_context():
        async with factory() as restarted, restarted.begin():
            yield restarted

    monkeypatch.setattr(event_source_tasks, "get_worker_db_context", restarted_context)
    for dispatch in dispatches:
        for _attempt in range(2):
            await event_source_tasks.dispatch_source_event(
                DispatchSourceEvent(
                    organization_id=ctx.organization_id,
                    dispatch_id=dispatch.id,
                )
            )
        await db.refresh(dispatch)
    runs = list(await db.scalars(select(WorkflowRun)))
    assert len(runs) == 2
    assert {run.workflow_id for run in runs} == {first_workflow.id, second_workflow.id}
    assert {run.workflow_version_id for run in runs} == {
        first.exposure.workflow_version_id,
        second.exposure.workflow_version_id,
    }
    assert all(run.input == {"body": receipt.body, "delivery_id": "event-1"} for run in runs)
    assert all(row.status == "admitted" for row in dispatches)


async def test_concurrent_duplicate_admission_persists_one_receipt_and_dispatch(
    db, engine, source_world
):
    _, _, _, source = source_world
    await _subscribed(db, source_world)
    source_id = source.id
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def deliver():
        async with factory() as session, session.begin():
            _, _, accepted = await _receive(session, source_id)
            return accepted

    admitted = await asyncio.gather(deliver(), deliver())
    assert sorted(admitted) == [False, True]
    assert await _count(db, EventDelivery) == 1
    assert await _count(db, EventDispatch) == 1


async def test_detaching_one_workflow_during_receipt_keeps_the_other_dispatch(
    db: AsyncSession, engine: AsyncEngine, source_world, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _, _, source = source_world
    _, removed = await _subscribed(db, source_world)
    _, kept = await _subscribed(db, source_world)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    reading_targets = anyio.Event()
    removing = anyio.Event()
    detached = anyio.Event()
    get_exposure = module.exposure_repo.get_by_id

    async def read_target(session: AsyncSession, exposure_id: UUID):
        reading_targets.set()
        await removing.wait()
        with anyio.move_on_after(0.2):
            await detached.wait()
        return await get_exposure(session, exposure_id)

    monkeypatch.setattr(module.exposure_repo, "get_by_id", read_target)

    async def receive() -> None:
        async with factory.begin() as session:
            assert (await _receive(session, source.id))[2]

    async def detach() -> None:
        await reading_targets.wait()
        async with factory.begin() as session:
            removing.set()
            await EventSourceService(session).unbind_workflow(removed.exposure.id)
        detached.set()

    with anyio.fail_after(8):
        async with anyio.create_task_group() as group:
            group.start_soon(receive)
            group.start_soon(detach)

    rows = (await db.scalars(select(EventDispatch))).all()
    assert len(rows) == 2
    assert sum(row.subscription_id is None for row in rows) == 1
    for row in rows:
        await EventSourceService(db).dispatch(ctx.organization_id, row.id)
    assert [run.workflow_version_id for run in await db.scalars(select(WorkflowRun))] == [
        kept.exposure.workflow_version_id
    ]


@pytest.mark.parametrize("detach_first", [True, False])
async def test_waiting_workflow_dispatch_reads_state_after_the_workflow_lock(
    db: AsyncSession,
    engine: AsyncEngine,
    source_world,
    monkeypatch: pytest.MonkeyPatch,
    detach_first: bool,
) -> None:
    ctx, _, _, source = source_world
    _, published = await _subscribed(db, source_world)
    await _receive(db, source.id)
    dispatch_id = await db.scalar(select(EventDispatch.id))
    assert dispatch_id is not None
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    entering_workflow_lock = anyio.Event()

    async def track_lock(session: AsyncSession, scope: LockScope, subject_id: UUID) -> None:
        entering_workflow_lock.set()
        await hold_subject(session, scope, subject_id)

    monkeypatch.setattr(module, "hold_subject", track_lock)
    # The actual admission lock is the first attempt on the old, deadlocking path.
    monkeypatch.setattr("app.services.workflow_execution.facade.hold_subject", track_lock)

    async def dispatch() -> None:
        async with factory.begin() as session:
            await EventSourceService(session).dispatch(ctx.organization_id, dispatch_id)

    with anyio.fail_after(8):
        async with anyio.create_task_group() as group, factory.begin() as publishing:
            await hold_subject(publishing, LockScope.WORKFLOW_FILE_BYTES, ctx.organization_id)
            group.start_soon(dispatch)
            await entering_workflow_lock.wait()
            service = EventSourceService(publishing)
            if detach_first:
                await service.unbind_workflow(published.exposure.id)
            else:
                await service.dispatch(ctx.organization_id, dispatch_id)

    row = await db.get(EventDispatch, dispatch_id, populate_existing=True)
    assert row is not None
    assert row.status == ("skipped" if detach_first else "admitted")
    assert (row.subscription_id is None) == detach_first
    assert await _count(db, WorkflowRun) == (0 if detach_first else 1)


@pytest.mark.parametrize("fits_after_cleanup", [True, False])
async def test_workflow_dispatch_only_retries_storage_refusals_that_can_clear(
    db: AsyncSession, source_world, monkeypatch: pytest.MonkeyPatch, fits_after_cleanup: bool
) -> None:
    ctx, _, _, source = source_world
    await _subscribed(db, source_world)
    _, first, _ = await _receive(db, source.id, "first")
    _, second, _ = await _receive(db, source.id, "later")
    first_dispatch = await db.scalar(
        select(EventDispatch).where(EventDispatch.delivery_id == first.id)
    )
    second_dispatch = await db.scalar(
        select(EventDispatch).where(EventDispatch.delivery_id == second.id)
    )
    assert first_dispatch is not None and second_dispatch is not None
    service = EventSourceService(db)
    await service.dispatch(ctx.organization_id, first_dispatch.id)
    running = await db.scalar(select(WorkflowRun))
    assert running is not None and running.inline_result_bytes > 1
    ceiling = running.inline_result_bytes - (0 if fits_after_cleanup else 1)
    monkeypatch.setattr(settings, "WORKFLOW_ORG_MAX_INLINE_RESULT_BYTES", ceiling)
    await service.dispatch(ctx.organization_id, second_dispatch.id)
    assert await _count(db, WorkflowRun) == 1
    if fits_after_cleanup:
        assert second_dispatch.status == "pending"
        running.inline_result_bytes = 0
        await db.flush()
        await service.dispatch(ctx.organization_id, second_dispatch.id)
        assert second_dispatch.status == "admitted"
        assert await _count(db, WorkflowRun) == 2
    else:
        assert second_dispatch.status == "failed"
        assert second_dispatch.error_code == "WORKFLOW_INLINE_STORAGE_LIMIT"


@pytest.mark.parametrize(
    "age,delay", [(timedelta(), timedelta(minutes=1)), (timedelta(days=1), timedelta(minutes=15))]
)
async def test_subscriber_at_capacity_retries_and_admits_the_waiting_delivery_once(
    db, source_world, age, delay
):
    ctx, _, _, source = source_world
    workflow, _ = await _subscribed(db, source_world)
    await WorkflowRegistryService(db).update_settings(
        ctx, workflow.id, WorkflowSettings(max_concurrent_runs=1)
    )
    _, first, _ = await _receive(db, source.id, "first")
    _, waiting, _ = await _receive(db, source.id, "waiting")
    active = await db.scalar(select(EventDispatch).where(EventDispatch.delivery_id == first.id))
    pending = await db.scalar(select(EventDispatch).where(EventDispatch.delivery_id == waiting.id))
    pending.created_at -= age
    await EventSourceService(db).dispatch(ctx.organization_id, active.id)
    running = await db.scalar(select(WorkflowRun))
    await db.commit()

    handlers = by_kind([Handler(DISPATCH_SOURCE_EVENT, event_source_tasks.dispatch_source_event)])
    payload = DispatchSourceEvent(organization_id=ctx.organization_id, dispatch_id=pending.id)
    raw = DISPATCH_SOURCE_EVENT.dump(payload)
    for _replay in range(2):
        assert isinstance(await run_handler(handlers, DISPATCH_SOURCE_EVENT.kind, raw), Succeeded)
    await db.refresh(pending)
    assert pending.status == "pending" and pending.completed_at is None
    assert await _count(db, WorkflowRun) == 1
    retries = list(
        await db.scalars(
            select(BackgroundJob).where(BackgroundJob.dedupe_key == f"event-dispatch:{pending.id}")
        )
    )
    assert len(retries) == 1
    retry = retries[0]
    assert retry.status == "queued"
    assert abs(retry.run_after - retry.created_at - delay) < timedelta(seconds=5)
    running.status = "succeeded"
    await db.commit()

    for _attempt in range(2):
        assert isinstance(await run_handler(handlers, retry.kind, retry.payload), Succeeded)
    await db.refresh(pending)
    assert pending.status == "admitted"
    runs = list(await db.scalars(select(WorkflowRun).where(WorkflowRun.id != running.id)))
    assert [run.input for run in runs] == [{"body": waiting.body, "delivery_id": "waiting"}]


@pytest.mark.parametrize("second_target", ["routine", "workflow"])
async def test_concurrent_attachments_to_one_source_both_commit(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, second_target: str
) -> None:
    """A second attachment must wait before acquiring a conflicting foreign-key or audit lock."""
    ctx, existing, _, _ = await world(db)
    source = await EventSourceService(db).create(ctx, EventSourceCreate(name="Shared events"))
    owner = await db.get(User, ctx.subject_id)
    org = await db.get(Organization, ctx.organization_id)
    assert owner is not None and org is not None
    workflow = await _workflow(db, org=org, owner=owner)
    workflow.draft_graph = _graph("trigger.webhook", {"source_id": str(source.id)}).model_dump(
        mode="json"
    )
    workflow_id, revision = workflow.id, workflow.draft_revision
    source_id, agent_id = source.id, existing.agent_id
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    entered_binder = anyio.Event()
    release_binder = anyio.Event()
    original_bind = EventSourceService.bind_routine

    async with sessions() as first, sessions() as second:
        second_pid = await second.scalar(text("SELECT pg_backend_pid()"))

        async def pause_first_binder(
            service: EventSourceService, actor: AuthContext, selected: UUID, trigger_id: UUID
        ) -> None:
            if service.db is first:
                entered_binder.set()
                await release_binder.wait()
            await original_bind(service, actor, selected, trigger_id)

        monkeypatch.setattr(EventSourceService, "bind_routine", pause_first_binder)

        async def create_routine(session: AsyncSession) -> None:
            await AgentTriggerService(session).create(
                ctx,
                agent_id,
                TriggerCreate(trigger_type="event", source_id=source_id, prompt="Process event"),
            )
            await session.commit()

        async def attach_second() -> None:
            if second_target == "routine":
                await create_routine(second)
            else:
                await WorkflowRegistryService(second).publish(
                    ctx, workflow_id, WorkflowPublish(expected_revision=revision)
                )
                await second.commit()

        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(create_routine, first)
                await entered_binder.wait()
                group.start_soon(attach_second)
                for _ in range(500):
                    if await db.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": second_pid}
                    ):
                        break
                    await anyio.sleep(0.01)
                else:
                    pytest.fail("The second attachment did not wait on PostgreSQL")
                release_binder.set()

    subscriptions = list(
        await db.scalars(select(EventSubscription).where(EventSubscription.source_id == source_id))
    )
    assert len(subscriptions) == 2
    assert sum(sub.trigger_id is not None for sub in subscriptions) == (
        2 if second_target == "routine" else 1
    )


async def test_queue_failure_rolls_back_receipt_and_partial_dispatch(db, source_world, monkeypatch):
    _, _, _, source = source_world
    await _subscribed(db, source_world)
    monkeypatch.setattr(module, "enqueue", AsyncMock(side_effect=RuntimeError("Queue unavailable")))
    with pytest.raises(RuntimeError, match="Queue unavailable"):
        async with db.begin_nested():
            await _receive(db, source.id)
    assert await _count(db, EventDelivery) == 0
    assert await _count(db, EventDispatch) == 0


@pytest.mark.security
async def test_one_subscriber_losing_authority_does_not_block_another(db, source_world):
    ctx, _, _, source = source_world
    denied, _ = await _subscribed(db, source_world)
    allowed, _ = await _subscribed(db, source_world)
    await _receive(db, source.id)
    denied.status = "archived"
    await db.flush()
    dispatches = list(await db.scalars(select(EventDispatch)))
    for row in dispatches:
        await EventSourceService(db).dispatch(ctx.organization_id, row.id)
    runs = list(await db.scalars(select(WorkflowRun)))
    assert [run.workflow_id for run in runs] == [allowed.id]
    assert sorted(row.status for row in dispatches) == ["admitted", "failed"]


async def test_republish_preserves_queued_subscription_version_and_principal(db, source_world):
    ctx, org, _, source = source_world
    workflow, published = await _subscribed(db, source_world)
    await _receive(db, source.id)
    dispatch = await db.scalar(select(EventDispatch))
    snapshot = dispatch.workflow_version_id
    new_publisher = await _user(db)
    await _member(db, org=org, user=new_publisher, role="owner")
    graph = WorkflowGraph.model_validate(workflow.draft_graph)
    second = await _publish(db, _ctx(new_publisher, org), workflow, graph)
    assert second.exposure.id == published.exposure.id
    assert second.exposure.workflow_version_id != snapshot
    await EventSourceService(db).dispatch(ctx.organization_id, dispatch.id)
    assert dispatch.status == "admitted"
    run = await db.scalar(select(WorkflowRun))
    assert run.workflow_version_id == snapshot
    assert run.execution_principal_user_id == ctx.user_id
    assert snapshot == published.exposure.workflow_version_id


@pytest.mark.security
async def test_source_visibility_and_tenant_are_independent_from_target_access(db, source_world):
    ctx, _, user, source = source_world
    other_org = await _org(db, owner=user)
    other = _ctx(user, other_org)
    with pytest.raises(NotFoundError):
        await EventSourceService(db).require_use(other, source.id)
    assert (await EventSourceService(db).require_use(ctx, source.id)).id == source.id


@pytest.mark.security
async def test_database_refuses_cross_tenant_source_credentials_deliveries_and_targets(
    db, source_world
):
    ctx, _, user, source = source_world
    _, published = await _subscribed(db, source_world)
    other_org = await _org(db, owner=user)
    other_source = await EventSourceService(db).create(
        _ctx(user, other_org), EventSourceCreate(name="Other source")
    )
    await EventSourceService(db).unbind_workflow(published.exposure.id)
    unused_credential = EventSourceCredential(
        organization_id=ctx.organization_id,
        sealed_secret="opaque",
        secret_key_version=1,
    )
    db.add(unused_credential)
    await db.flush()
    wrong_rows = [
        (
            EventSource(
                organization_id=other_org.id,
                owner_user_id=user.id,
                name="Wrong",
                provider="webhook",
                auth={},
                visibility="private",
                is_active=True,
                secret_id=unused_credential.id,
            ),
            "fk_event_source_credential_tenant",
        ),
        (
            EventDelivery(organization_id=other_org.id, source_id=source.id, body={}),
            "fk_event_delivery_source_tenant",
        ),
        (
            EventSubscription(
                organization_id=other_org.id,
                source_id=other_source.id,
                exposure_id=published.exposure.id,
            ),
            "fk_event_subscription_exposure_tenant",
        ),
        (
            EventSubscription(
                organization_id=ctx.organization_id,
                source_id=other_source.id,
                exposure_id=published.exposure.id,
            ),
            "fk_event_subscription_source_tenant",
        ),
    ]
    for row, constraint in wrong_rows:
        with pytest.raises(IntegrityError, match=constraint):
            async with db.begin_nested():
                db.add(row)
                await db.flush()
    assert await _count(db, EventSource) == 2
    assert await _count(db, EventDelivery) == 0
    assert await _count(db, EventSubscription) == 0


@pytest.mark.security
async def test_private_source_grants_allow_use_without_promoting_source_edit(db, source_world):
    ctx, org, owner, source = source_world
    viewer = await _user(db)
    await _member(db, org=org, user=viewer, role="viewer")
    viewer_ctx = _ctx(viewer, org, "viewer")
    service = EventSourceService(db)
    assert (await service.list(viewer_ctx)).items == []
    with pytest.raises(NotFoundError):
        await service.require_use(viewer_ctx, source.id)
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=viewer.id,
            resource_type="event_source",
            resource_id=source.id,
            level="use",
            created_by_user_id=owner.id,
        )
    )
    await db.flush()
    assert (await service.require_use(viewer_ctx, source.id)).id == source.id
    read = (await service.list(viewer_ctx)).items[0]
    assert read.can_use and not read.can_edit
    with pytest.raises(NotFoundError):
        await service.delete(viewer_ctx, source.id)
    assert (await service.list(ctx)).total == 1


async def test_deleting_an_unused_source_also_removes_its_credential(db, source_world):
    ctx, _, _, source = source_world
    await _receive(db, source.id)
    await EventSourceService(db).delete(ctx, source.id)
    assert await _count(db, EventSource) == 0
    assert await _count(db, EventSourceCredential) == 0
    assert await _count(db, EventDelivery) == 0


async def test_subscription_deletion_preserves_dispatch_history_and_source_deletion_is_blocked(
    db, source_world
):
    ctx, _, _, source = source_world
    _, published = await _subscribed(db, source_world)
    await _receive(db, source.id)
    with pytest.raises(BadRequestError, match="Detach"):
        await EventSourceService(db).delete(ctx, source.id)
    dispatch = await db.scalar(select(EventDispatch))
    await EventSourceService(db).unbind_workflow(published.exposure.id)
    await db.refresh(dispatch)
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert dispatch.subscription_id is None
    assert dispatch.organization_id == ctx.organization_id


async def test_static_credentials_without_delivery_id_do_not_deduplicate_distinct_requests(
    db, source_world
):
    _, _, _, source = source_world
    assert (await _receive(db, source.id, None))[2]
    assert (await _receive(db, source.id, None))[2]
    assert await _count(db, EventDelivery) == 2


async def test_cleanup_keeps_pending_payloads_and_clears_terminal_payloads_only(db, source_world):
    ctx, _, _, source = source_world
    await _subscribed(db, source_world)
    await _receive(db, source.id)
    receipt = await db.scalar(select(EventDelivery))
    receipt.created_at = datetime.now(UTC) - timedelta(days=400)
    await db.flush()
    await EventSourceService(db).cleanup()
    await db.refresh(receipt)
    assert receipt.body is not None
    dispatch = await db.scalar(select(EventDispatch))
    await EventSourceService(db).dispatch(ctx.organization_id, dispatch.id)
    await EventSourceService(db).cleanup()
    await db.refresh(receipt)
    assert receipt.body is None and receipt.headers == {}


async def test_organization_deletion_removes_its_sources_and_accepted_work(db, source_world):
    _, org, _, source = source_world
    await _subscribed(db, source_world)
    await _receive(db, source.id)
    await db.delete(org)
    await db.flush()
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert await _count(db, EventSource) == 0
    assert await _count(db, EventDelivery) == 0
    assert await _count(db, EventDispatch) == 0


@pytest.mark.parametrize(
    "job_state", ["queued", "running", "dead", "cancelled", "succeeded", "missing"]
)
async def test_retention_keeps_live_work_and_releases_only_abandoned_pending_payloads(
    db, source_world, job_state, monkeypatch
):
    _, _, _, source = source_world
    await _subscribed(db, source_world)
    await _receive(db, source.id)
    receipt = await db.scalar(select(EventDelivery))
    dispatch = await db.scalar(select(EventDispatch))
    job = await db.scalar(
        select(BackgroundJob).where(BackgroundJob.kind == "dispatch-source-event")
    )
    old = datetime.now(UTC) - timedelta(days=400)
    receipt.created_at = old
    dispatch.created_at = old
    if job_state == "missing":
        await db.delete(job)
    else:
        job.status = job_state
    await db.flush()

    @asynccontextmanager
    async def cleanup_context():
        yield db

    monkeypatch.setattr(event_source_tasks, "get_worker_db_context", cleanup_context)
    await event_source_tasks.cleanup_source_deliveries()
    await db.refresh(receipt)
    await db.refresh(dispatch)
    if job_state in {"queued", "running"}:
        assert receipt.body is not None
        assert dispatch.status == "pending"
        assert dispatch.completed_at is None
    else:
        assert receipt.body is None
        assert dispatch.status == "failed"
        assert dispatch.error_code == "DISPATCH_JOB_TERMINAL"
        assert dispatch.completed_at is not None
