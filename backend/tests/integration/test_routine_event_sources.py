"""Real PostgreSQL routine admissions for dedicated and shared webhook sources."""

import hmac
import json
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid5

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import ConflictError
from app.db.models.agent_run import AgentRun
from app.db.models.agent_trigger import TriggerAttempt
from app.db.models.background_job import BackgroundJob
from app.db.models.event_source import EventDelivery, EventDispatch, EventSubscription
from app.db.models.organization import Organization
from app.db.models.resource_grant import ResourceGrant
from app.repositories import event_source as source_repo
from app.schemas.agent_trigger import TriggerCreate, TriggerUpdate
from app.schemas.event_source import EventSourceCreate, SourceAuth, SourceCredentials
from app.schemas.routine_sources import RoutineSourceConsent, RoutineSourceItem
from app.services import rate_limit
from app.services.agent_trigger import AgentTriggerService
from app.services.event_sources import EventSourceService
from app.services.routine_sources import RoutineSourceService, RoutineSourcesRequired, read_policy
from app.worker.jobs import FireTrigger
from tests.integration.test_routine_sources import world
from tests.integration.test_workflow_exposures import _ctx, _member, _user

pytestmark = pytest.mark.anyio


@pytest.mark.security
@pytest.mark.parametrize("overlap", ["receipt", "dispatch"])
async def test_rebinding_during_delivery_preserves_the_other_subscriber_and_retires_consent(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, overlap: str
) -> None:
    ctx, seed, _, _ = await world(db)
    sources = EventSourceService(db)
    config = EventSourceCreate(
        name="Original",
        auth=SourceAuth(method="api_key", header_name="x-api-key", signature_prefix=""),
        credentials=SourceCredentials(secret=SecretStr("test-key")),
    )
    source = await sources.create(ctx, config)
    other = await sources.create(ctx, config.model_copy(update={"name": "Other"}))
    triggers = AgentTriggerService(db)
    spec = TriggerCreate(trigger_type="event", source_id=source.id, prompt="One routine")
    moving = await triggers.create(ctx, seed.agent_id, spec)
    sibling = await triggers.create(
        ctx, seed.agent_id, spec.model_copy(update={"prompt": "Another routine"})
    )
    subscription = await source_repo.target_subscription(db, trigger_id=moving.id)
    assert subscription is not None
    session = async_sessionmaker(engine, expire_on_commit=False)
    await db.commit()
    monkeypatch.setattr(
        rate_limit,
        "trigger_delivery_allowed",
        AsyncMock(return_value=rate_limit.Decision(allowed=True, retry_after_seconds=0)),
    )

    async def rebind() -> None:
        async with session.begin() as editor:
            await editor.execute(text("SET LOCAL lock_timeout = '3s'"))
            await AgentTriggerService(editor).update(
                ctx, seed.agent_id, moving.id, TriggerUpdate(source_id=other.id)
            )

    async def receive() -> None:
        _, _, admitted = await sources.receive(
            source.id, body=b"{}", headers={"x-api-key": "test-key"}
        )
        assert admitted

    with monkeypatch.context() as race:
        if overlap == "receipt":
            save = source_repo.save

            async def move_before_dispatch_insert(session, row):
                if isinstance(row, EventDispatch) and row.subscription_id == subscription.id:
                    await rebind()
                return await save(session, row)

            race.setattr(source_repo, "save", move_before_dispatch_insert)
            await receive()
        else:
            await receive()
            await db.commit()
            dispatch = await db.scalar(
                select(EventDispatch).where(EventDispatch.subscription_id == subscription.id)
            )
            assert dispatch is not None
            lock_dispatch_routine = source_repo.lock_dispatch_routine

            async def move_before_routine_lock(session, **kwargs):
                await rebind()
                await lock_dispatch_routine(session, **kwargs)

            race.setattr(source_repo, "lock_dispatch_routine", move_before_routine_lock)
            await sources.dispatch(ctx.organization_id, dispatch.id)
    await db.commit()
    await db.refresh(subscription)
    assert subscription.source_id == other.id
    await db.refresh(moving)
    assert not moving.is_active and moving.setup_required
    with pytest.raises(RoutineSourcesRequired):
        await triggers.update(ctx, seed.agent_id, moving.id, TriggerUpdate(is_active=True))
    _, paused_receipt, _ = await sources.receive(
        other.id, body=b"{}", headers={"x-api-key": "test-key"}
    )
    assert (
        await db.scalar(select(EventDispatch).where(EventDispatch.delivery_id == paused_receipt.id))
        is None
    )

    await triggers.update(ctx, seed.agent_id, moving.id, TriggerUpdate(source_id=source.id))
    review_service = RoutineSourceService(db)
    review = await review_service.options(ctx, moving)
    assert not review.current
    await review_service.replace(
        ctx, moving, RoutineSourceConsent(review_token=review.review_token)
    )
    await triggers.update(ctx, seed.agent_id, moving.id, TriggerUpdate(is_active=True))
    assert moving.is_active and not moving.setup_required
    dispatches = list(await db.scalars(select(EventDispatch)))
    assert len(dispatches) == 2
    for dispatch in dispatches:
        await sources.dispatch(ctx.organization_id, dispatch.id)
    assert sorted(row.status for row in dispatches) == ["admitted", "skipped"]
    jobs = list(await db.scalars(select(BackgroundJob).where(BackgroundJob.kind == "fire-trigger")))
    assert [FireTrigger.model_validate(job.payload).trigger_id for job in jobs] == [sibling.id]


async def test_shared_github_push_admits_one_routine_job_with_structured_input_across_restart(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, existing, _, _ = await world(db)
    source = await EventSourceService(db).create(
        ctx,
        EventSourceCreate(
            name="Repository pushes",
            provider="github",
            auth=SourceAuth(method="provider"),
            credentials=SourceCredentials(secret=SecretStr("integration-source-key")),
        ),
    )
    routine = await AgentTriggerService(db).create(
        ctx,
        existing.agent_id,
        TriggerCreate(
            trigger_type="event",
            source_id=source.id,
            event_config={"event": "push", "branches": ["main"]},
            prompt_mode="template",
            prompt="Review {{head_commit.message}}",
            runs_as_creator=True,
        ),
    )
    await db.refresh(routine)
    assert routine.is_active
    assert routine.source_id == source.id
    assert routine.event_source == "github" and routine.event_config["actions"] == []
    assert routine.event_secret_encrypted is None and routine.secret_key_version is None
    assert routine.prompt_mode == "template"
    policy_id = read_policy(routine.approved_sources).id
    subscription = await db.scalar(
        select(EventSubscription).where(EventSubscription.trigger_id == routine.id)
    )
    assert subscription is not None
    assert (subscription.source_id, subscription.organization_id) == (
        source.id,
        ctx.organization_id,
    )
    source_id, routine_id = source.id, routine.id
    await db.commit()

    monkeypatch.setattr(
        rate_limit,
        "trigger_delivery_allowed",
        AsyncMock(
            side_effect=[
                rate_limit.Decision(allowed=False, retry_after_seconds=30),
                rate_limit.Decision(allowed=True, retry_after_seconds=0),
            ]
        ),
    )
    body = {
        "ref": "refs/heads/main",
        "padding": "x" * 4000,
        "head_commit": {"message": "Beyond the old cutoff"},
    }
    encoded = json.dumps(body).encode()
    headers = {
        "x-github-event": "push",
        "x-github-delivery": "routine-delivery-1",
        "x-hub-signature-256": "sha256="
        + hmac.digest(b"integration-source-key", encoded, "sha256").hex(),
    }
    service = EventSourceService(db)
    _, receipt, accepted = await service.receive(source_id, body=encoded, headers=headers)
    _, _, repeated = await service.receive(source_id, body=encoded, headers=headers)
    assert accepted and not repeated
    receipt_id = receipt.id
    assert await db.scalar(select(func.count()).select_from(EventDelivery)) == 1
    dispatch = await db.scalar(select(EventDispatch))
    assert dispatch is not None and dispatch.subscription_id == subscription.id
    assert dispatch.routine_source_policy_id == policy_id
    dispatch_id = dispatch.id
    assert (
        await db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == "dispatch-source-event")
        )
        == 1
    )
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as throttled, throttled.begin():
        await EventSourceService(throttled).dispatch(ctx.organization_id, dispatch_id)
    await db.refresh(dispatch)
    assert dispatch.status == "pending" and dispatch.completed_at is None
    async with factory() as restarted, restarted.begin():
        service = EventSourceService(restarted)
        await service.dispatch(ctx.organization_id, dispatch_id)
        await service.dispatch(ctx.organization_id, dispatch_id)

    await db.refresh(dispatch)
    assert dispatch.status == "admitted"
    queued = list(
        await db.scalars(select(BackgroundJob).where(BackgroundJob.kind == "fire-trigger"))
    )
    assert len(queued) == 1
    payload = FireTrigger.model_validate(queued[0].payload)
    assert payload.trigger_id == routine_id
    assert payload.event_body == body
    assert payload.event_source_id == source_id
    assert payload.source_policy_id == policy_id
    assert payload.activation_id == uuid5(receipt_id, str(routine_id))
    assert queued[0].organization_id == ctx.organization_id

    _, _, repeated = await EventSourceService(db).receive(source_id, body=encoded, headers=headers)
    assert not repeated
    assert (
        await db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == "fire-trigger")
        )
        == 1
    )
    assert await db.scalar(select(func.count()).select_from(EventDispatch)) == 1
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0


@pytest.mark.security
async def test_creator_must_be_able_to_use_the_replacement_source_to_review_and_resume(
    db: AsyncSession,
) -> None:
    editor, seed, _, _ = await world(db)
    org = await db.get(Organization, editor.organization_id)
    assert org is not None
    member = await _user(db)
    await _member(db, org=org, user=member, role="member")
    creator = _ctx(member, org, "member")
    db.add(
        ResourceGrant(
            organization_id=org.id,
            resource_type="agent",
            resource_id=seed.agent_id,
            subject_user_id=member.id,
            level="edit",
            created_by_user_id=editor.subject_id,
        )
    )
    await db.flush()
    sources = EventSourceService(db)
    shared = await sources.create(editor, EventSourceCreate(name="Original", visibility="org"))
    private = await sources.create(editor, EventSourceCreate(name="Private replacement"))
    routines = AgentTriggerService(db)
    routine = await routines.create(
        creator,
        seed.agent_id,
        TriggerCreate(trigger_type="event", source_id=shared.id, prompt="Notify"),
    )
    await routines.update(editor, seed.agent_id, routine.id, TriggerUpdate(source_id=private.id))
    reviews = RoutineSourceService(db)
    blocked = await reviews.options(creator, routine)
    assert not blocked.current and blocked.unavailable_sources == ["event source"]
    assert private.name not in blocked.model_dump_json()
    with pytest.raises(ConflictError):
        await reviews.replace(
            creator, routine, RoutineSourceConsent(review_token=blocked.review_token)
        )
    assert not routine.is_active and routine.setup_required

    access = ResourceGrant(
        organization_id=org.id,
        resource_type="event_source",
        resource_id=private.id,
        subject_user_id=member.id,
        level="use",
        created_by_user_id=editor.subject_id,
    )
    db.add(access)
    await db.flush()
    allowed = await reviews.options(creator, routine)
    assert (
        RoutineSourceItem(kind="event_source", id=str(private.id), name=private.name)
        in allowed.items
    )
    await reviews.replace(creator, routine, RoutineSourceConsent(review_token=allowed.review_token))
    await db.delete(access)
    await db.flush()
    with pytest.raises(RoutineSourcesRequired):
        async with db.begin_nested():
            await routines.update(creator, seed.agent_id, routine.id, TriggerUpdate(is_active=True))
    await db.refresh(routine)
    assert not routine.is_active


@pytest.mark.security
@pytest.mark.parametrize("initial_review", ["present", "missing", "unavailable"])
async def test_source_delivery_requires_the_same_valid_review_at_receipt_and_dispatch(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, initial_review: str
) -> None:
    ctx, existing, _, account = await world(db, mcp=initial_review == "unavailable")
    sources = EventSourceService(db)
    source_config = EventSourceCreate(
        name="First",
        auth=SourceAuth(method="api_key", header_name="x-api-key", signature_prefix=""),
        credentials=SourceCredentials(secret=SecretStr("integration-source-key")),
    )
    source = await sources.create(ctx, source_config)
    triggers = AgentTriggerService(db)
    routine = await triggers.create(
        ctx,
        existing.agent_id,
        TriggerCreate(trigger_type="event", source_id=source.id, prompt="Review"),
    )
    policy_id = read_policy(routine.approved_sources).id
    reviews = RoutineSourceService(db)
    if initial_review == "missing":
        routine.approved_sources = None
        await db.flush()
    elif initial_review == "unavailable":
        assert account is not None
        account.is_enabled = False
        await db.flush()
    review = await reviews.options(ctx, routine)
    assert review.current == (initial_review == "present")

    _, _, accepted = await sources.receive(
        source.id, body=b"{}", headers={"x-api-key": "integration-source-key"}
    )
    assert accepted
    dispatch = await db.scalar(select(EventDispatch))
    assert dispatch is not None
    assert dispatch.routine_source_policy_id == (policy_id if initial_review == "present" else None)
    if initial_review == "unavailable":
        assert account is not None
        account.is_enabled = True
        await db.flush()
        assert (await reviews.options(ctx, routine)).current
    else:
        await reviews.replace(ctx, routine, RoutineSourceConsent(review_token=review.review_token))
        assert read_policy(routine.approved_sources).id != policy_id
    await db.commit()
    monkeypatch.setattr(
        rate_limit,
        "trigger_delivery_allowed",
        AsyncMock(return_value=rate_limit.Decision(allowed=True, retry_after_seconds=0)),
    )
    await sources.dispatch(ctx.organization_id, dispatch.id)
    assert dispatch.status == "skipped"
    assert (
        await db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "fire-trigger")) is None
    )
    attempt = await db.scalar(select(TriggerAttempt).where(TriggerAttempt.trigger_id == routine.id))
    assert attempt is not None and attempt.reason == "source_review_required"


async def test_deleting_a_routine_detaches_it_and_preserves_its_accepted_receipt(
    db: AsyncSession,
) -> None:
    ctx, seed, _, _ = await world(db)
    sources = EventSourceService(db)
    source = await sources.create(
        ctx,
        EventSourceCreate(
            name="Events",
            auth=SourceAuth(method="api_key", header_name="x-key", signature_prefix=""),
            credentials=SourceCredentials(secret=SecretStr("test-key")),
        ),
    )
    triggers = AgentTriggerService(db)
    routine = await triggers.create(
        ctx,
        seed.agent_id,
        TriggerCreate(trigger_type="event", source_id=source.id, prompt="Review"),
    )
    _, receipt, accepted = await sources.receive(
        source.id, body=b"{}", headers={"x-key": "test-key"}
    )
    assert accepted
    routine_id = routine.id
    await triggers.delete(ctx, seed.agent_id, routine_id)
    await db.commit()
    assert await source_repo.target_subscription(db, trigger_id=routine_id) is None
    dispatch = await db.scalar(select(EventDispatch).where(EventDispatch.delivery_id == receipt.id))
    assert dispatch is not None and dispatch.subscription_id is None
    await sources.dispatch(ctx.organization_id, dispatch.id)
    assert dispatch.status == "skipped"
    assert (
        await db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "fire-trigger")) is None
    )


async def test_dedicated_webhooks_preserve_literal_input_and_validate_template_input(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, existing, _, _ = await world(db)
    service = AgentTriggerService(db)
    secret = "integration-routine-secret"
    literal_data = TriggerCreate(
        trigger_type="event",
        event_source="webhook",
        event_secret=secret,
        prompt="Review the delivery",
        runs_as_creator=True,
    )
    literal = await service.create(ctx, existing.agent_id, literal_data)
    template = await service.create(
        ctx,
        existing.agent_id,
        literal_data.model_copy(
            update={"prompt": "Review {{issue.title}}", "prompt_mode": "template"}
        ),
    )
    monkeypatch.setattr(
        rate_limit,
        "trigger_delivery_allowed",
        AsyncMock(return_value=rate_limit.Decision(allowed=True, retry_after_seconds=0)),
    )

    escaped_nul = b'{"nested":{"text":"before\\u0000after"}}'
    structured = {"padding": "x" * 4000, "issue": {"title": "Full payload"}}
    for trigger, body in (
        (literal, escaped_nul),
        (template, escaped_nul),
        (template, json.dumps(structured).encode()),
    ):
        signature = hmac.digest(secret.encode(), body, "sha256").hex()
        assert await service.queue_event_fire(
            "webhook",
            trigger.id,
            body=body,
            headers={"x-signature-256": f"sha256={signature}"},
        )

    jobs = await db.scalars(select(BackgroundJob).where(BackgroundJob.kind == "fire-trigger"))
    queued = [FireTrigger.model_validate(job.payload) for job in jobs]
    assert len(queued) == 2
    by_trigger = {job.trigger_id: job for job in queued}
    literal_job = by_trigger[literal.id]
    assert literal_job.event_body is None
    assert literal_job.event_context is not None
    assert "before\\u0000after" in literal_job.event_context
    assert by_trigger[template.id].event_body == structured

    failed = await db.scalar(select(TriggerAttempt).where(TriggerAttempt.trigger_id == template.id))
    assert failed is not None
    assert (failed.stage, failed.status, failed.reason) == (
        "preparation",
        "failed",
        "prompt_template_failed",
    )
    assert failed.error_message == "The event body cannot be stored for prompt rendering."
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0


@pytest.mark.security
@pytest.mark.parametrize("approval", ["current", "missing", "replaced"])
async def test_shared_github_filter_keeps_only_the_current_reviews_diagnostic(
    db: AsyncSession, approval: str
) -> None:
    ctx, existing, _, _ = await world(db)
    sources = EventSourceService(db)
    source = await sources.create(
        ctx,
        EventSourceCreate(
            name="GitHub",
            provider="github",
            auth=SourceAuth(method="provider"),
            credentials=SourceCredentials(secret=SecretStr("github-secret")),
        ),
    )
    triggers = AgentTriggerService(db)
    routine = await triggers.create(
        ctx,
        existing.agent_id,
        TriggerCreate(
            trigger_type="event",
            source_id=source.id,
            prompt="Review",
            event_config={"authors": "members"},
        ),
    )
    if approval == "missing":
        routine.approved_sources = None
        await db.flush()
    body = b'{"action":"opened","issue":{"author_association":"NONE"}}'
    headers = {
        "x-github-event": "issues",
        "x-hub-signature-256": "sha256=" + hmac.digest(b"github-secret", body, "sha256").hex(),
    }
    _, receipt, accepted = await sources.receive(source.id, body=body, headers=headers)
    assert accepted
    if approval == "replaced":
        reviews = RoutineSourceService(db)
        review = await reviews.options(ctx, routine)
        await reviews.replace(ctx, routine, RoutineSourceConsent(review_token=review.review_token))
    received_at = await db.scalar(
        select(EventDelivery.created_at).where(EventDelivery.id == receipt.id)
    )
    dispatch = await db.scalar(select(EventDispatch))
    assert dispatch is not None
    await sources.dispatch(ctx.organization_id, dispatch.id)
    await db.refresh(routine)
    assert dispatch.status == "skipped"
    if approval != "current":
        assert routine.last_filtered_event is None
        return
    assert routine.last_filtered_event is not None
    assert datetime.fromisoformat(routine.last_filtered_event["received_at"]) == received_at
    assert routine.last_filtered_event["reason"] == "author"
    assert routine.last_filtered_event["authors"] == "members"
