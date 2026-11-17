"""A shared source queues a real routine transaction with its complete event body."""

import json
from unittest.mock import AsyncMock
from uuid import uuid5

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent_run import AgentRun
from app.db.models.background_job import BackgroundJob
from app.db.models.event_source import EventDelivery, EventDispatch, EventSubscription
from app.schemas.agent_trigger import TriggerCreate
from app.schemas.event_source import EventSourceCreate, SourceAuth, SourceCredentials
from app.services import rate_limit
from app.services.agent_trigger import AgentTriggerService
from app.services.event_sources import EventSourceService
from app.services.routine_sources import read_policy
from app.worker.jobs import FireTrigger
from tests.integration.test_routine_sources import world

pytestmark = pytest.mark.anyio


async def test_shared_source_admits_one_routine_job_with_structured_input_across_restart(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, existing, _, _ = await world(db)
    source = await EventSourceService(db).create(
        ctx,
        EventSourceCreate(
            name="Routine events",
            auth=SourceAuth(method="api_key", header_name="x-api-key", signature_prefix=""),
            credentials=SourceCredentials(secret=SecretStr("integration-source-key")),
        ),
    )
    routine = await AgentTriggerService(db).create(
        ctx,
        existing.agent_id,
        TriggerCreate(
            trigger_type="event",
            source_id=source.id,
            prompt_mode="template",
            prompt="Review {{issue.title}} and {{values[0]}}",
            runs_as_creator=True,
        ),
    )
    await db.refresh(routine)
    assert routine.is_active
    assert routine.source_id == source.id
    assert routine.event_source == "webhook"
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
        AsyncMock(return_value=rate_limit.Decision(allowed=True, retry_after_seconds=0)),
    )
    body = {
        "padding": "x" * 4000,
        "issue": {"title": "Beyond the old cutoff"},
        "values": [False, 0, None],
    }
    headers = {"x-api-key": "integration-source-key", "x-delivery-id": "routine-delivery-1"}
    service = EventSourceService(db)
    _, receipt, accepted = await service.receive(
        source_id, body=json.dumps(body).encode(), headers=headers
    )
    _, _, repeated = await service.receive(
        source_id, body=json.dumps(body).encode(), headers=headers
    )
    assert accepted and not repeated
    receipt_id = receipt.id
    assert await db.scalar(select(func.count()).select_from(EventDelivery)) == 1
    dispatch = await db.scalar(select(EventDispatch))
    assert dispatch is not None and dispatch.subscription_id == subscription.id
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

    _, _, repeated = await EventSourceService(db).receive(
        source_id, body=json.dumps(body).encode(), headers=headers
    )
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
