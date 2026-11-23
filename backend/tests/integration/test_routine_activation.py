"""Exact activation lookups retain tenant and root-run isolation beyond a page."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.conversation import Conversation
from app.repositories.agent_run import RunFilters, list_runs, run_id_for_routine_activation
from app.services.agent_trigger import AgentTriggerService
from tests.integration.test_knowledge_gaps import _agent, _owner
from tests.integration.test_routine_sources import world

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("cancelled", [False, True])
async def test_failed_fire_clears_committed_lease_despite_outer_rollback(
    db: AsyncSession, cancelled: bool
) -> None:
    _, trigger, _, _ = await world(db)
    trigger_id = trigger.id
    ticket = datetime.now(UTC)
    trigger.fire_in_flight_since = ticket
    await db.commit()

    async def fail_with_row_lock(*args: object, **kwargs: object) -> None:
        trigger.name = "Uncommitted delivery"
        await db.flush()
        if cancelled:
            raise asyncio.CancelledError()
        raise RuntimeError("Delivery persistence failed")

    service = AgentTriggerService(db)
    with (
        patch.object(service, "_fire_loaded", AsyncMock(side_effect=fail_with_row_lock)),
        pytest.raises(asyncio.CancelledError if cancelled else RuntimeError),
    ):
        await asyncio.wait_for(service.fire(trigger_id, claimed_at=ticket), timeout=5)
    await db.rollback()
    saved = await db.get(AgentTrigger, trigger_id)
    assert saved is not None
    assert saved.fire_in_flight_since is None
    assert saved.name is None


@pytest.mark.security
@pytest.mark.parametrize("root_matches", [False, True])
async def test_activation_lookup_is_not_a_history_page_or_another_tenants_run(
    db: AsyncSession,
    root_matches: bool,
) -> None:
    owner, other = await _owner(db), await _owner(db)
    agent, foreign = await _agent(db, owner), await _agent(db, other)
    conversation = Conversation(
        organization_id=owner.organization_id, user_id=owner.user_id, title="Activation history"
    )
    db.add(conversation)
    await db.flush()
    activation, origin, foreign_origin = uuid4(), uuid4(), uuid4()
    start = datetime(2026, 11, 16, tzinfo=UTC)
    root = AgentRun(
        id=uuid4(),
        organization_id=owner.organization_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        surface="schedule",
        status="completed",
        started_at=start,
        routine_origin_id=origin,
        routine_policy={"activation_id": str(activation if root_matches else uuid4())},
        cost_usd=Decimal(0),
        input_tokens=0,
        output_tokens=0,
    )
    db.add(root)
    await db.flush()
    db.add(
        AgentRun(
            id=uuid4(),
            organization_id=owner.organization_id,
            agent_id=agent.id,
            parent_run_id=root.id,
            surface="delegate",
            status="completed",
            started_at=start,
            routine_origin_id=origin,
            routine_policy={"activation_id": str(activation)},
            cost_usd=Decimal(0),
            input_tokens=0,
            output_tokens=0,
        )
    )
    db.add(
        AgentRun(
            id=uuid4(),
            organization_id=other.organization_id,
            agent_id=foreign.id,
            surface="schedule",
            status="completed",
            started_at=start,
            routine_origin_id=foreign_origin,
            routine_policy={"activation_id": str(activation)},
            cost_usd=Decimal(0),
            input_tokens=0,
            output_tokens=0,
        )
    )
    for minute in range(1, 52):
        db.add(
            AgentRun(
                id=uuid4(),
                organization_id=owner.organization_id,
                agent_id=agent.id,
                conversation_id=conversation.id,
                surface="schedule",
                status="completed",
                started_at=start + timedelta(minutes=minute),
                routine_origin_id=origin,
                routine_policy={"activation_id": str(uuid4())},
                cost_usd=Decimal(0),
                input_tokens=0,
                output_tokens=0,
            )
        )
    await db.flush()
    first_page, total = await list_runs(
        db,
        organization_id=owner.organization_id,
        filters=RunFilters(conversation_id=conversation.id),
    )
    assert total == 52 and root.id not in {run.id for run in first_page}
    assert await run_id_for_routine_activation(
        db, organization_id=owner.organization_id, trigger_id=origin, activation_id=activation
    ) == (root.id if root_matches else None)
    assert (
        await run_id_for_routine_activation(
            db, organization_id=other.organization_id, trigger_id=origin, activation_id=activation
        )
        is None
    )
