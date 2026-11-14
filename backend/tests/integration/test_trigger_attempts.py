"""Before-run failures remain visible without retaining provider errors or prompts."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import PlatformMcpServerRef
from app.core.exceptions import NotFoundError
from app.db.models.agent import AgentVersion
from app.db.models.agent_run import AgentRun
from app.repositories import agent_trigger_repo
from app.services.agent_trigger import AgentTriggerService
from app.services.routine_sources import (
    PlatformRoutineIdentityRequired,
    RoutineSourceService,
    RoutineSourcesRequired,
    read_policy,
)
from app.worker.jobs import FireTrigger
from tests.integration.test_routine_sources import world

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_attempt_identity_pagination_and_tenant_isolation(db: AsyncSession) -> None:
    ctx, trigger, _, _ = await world(db)
    activation = uuid4()
    first = await agent_trigger_repo.record_attempt(
        db,
        trigger_id=trigger.id,
        organization_id=ctx.organization_id,
        activation_id=activation,
        status="blocked",
        stage="source_review",
        reason="source_review_required",
    )
    duplicate = await agent_trigger_repo.record_attempt(
        db,
        trigger_id=trigger.id,
        organization_id=ctx.organization_id,
        activation_id=activation,
        status="failed",
        stage="preparation",
        reason="preparation_failed",
    )
    assert first.id == duplicate.id and duplicate.status == "blocked"
    service = AgentTriggerService(db)
    with patch.object(service, "fire", AsyncMock()) as fire:
        repeated = await service.fire_job(
            FireTrigger(
                trigger_id=trigger.id,
                activation_id=activation,
                source_policy_id=read_policy(trigger.approved_sources).id,
            )
        )
    assert repeated.outcome == "blocked" and repeated.attempt_id == first.id
    fire.assert_not_awaited()
    assert (
        await agent_trigger_repo.list_attempts(
            db, trigger_id=trigger.id, organization_id=uuid4(), skip=0, limit=50
        )
    ) == ([], 0)
    assert (
        await agent_trigger_repo.attempt_for_activation(
            db, trigger_id=trigger.id, organization_id=uuid4(), activation_id=activation
        )
        is None
    )
    page = await AgentTriggerService(db).attempts(
        ctx, trigger.agent_id, trigger.id, skip=0, limit=1
    )
    assert page.total == 1 and [row.id for row in page.items] == [first.id]
    empty = await AgentTriggerService(db).attempts(
        ctx, trigger.agent_id, trigger.id, skip=1, limit=1
    )
    assert empty.total == 1 and empty.items == []
    with pytest.raises(NotFoundError):
        await AgentTriggerService(db).attempts(ctx, trigger.agent_id, uuid4(), skip=0, limit=50)
    other_ctx, other_trigger, _, _ = await world(db)
    with pytest.raises(NotFoundError):
        await service.attempts(other_ctx, trigger.agent_id, trigger.id, skip=0, limit=50)
    with pytest.raises(NotFoundError):
        await service.attempts(ctx, trigger.agent_id, other_trigger.id, skip=0, limit=50)
    trigger.one_shot = True
    trigger.created_by_user_id = other_ctx.user_id
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.attempts(ctx, trigger.agent_id, trigger.id, skip=0, limit=50)


@pytest.mark.security
async def test_old_platform_policy_records_a_blocked_attempt_without_a_model_run(
    db: AsyncSession,
) -> None:
    ctx, trigger, spec, _ = await world(db)
    version = await db.get(AgentVersion, trigger.pinned_version_id)
    assert version is not None
    version.spec = spec.model_copy(
        update={"mcp_servers": [PlatformMcpServerRef(account="platform")]}
    ).model_dump(mode="json")
    trigger.runs_as_creator = False
    await db.flush()
    snapshot = await RoutineSourceService(db).snapshot(ctx, trigger)
    trigger.approved_sources = snapshot.policy.model_dump(mode="json")
    activation = uuid4()
    with patch("app.services.agent_runner.AgentRunnerService.execute", AsyncMock()) as execute:
        result = await AgentTriggerService(db).fire_job(
            FireTrigger(
                trigger_id=trigger.id, source_policy_id=snapshot.policy.id, activation_id=activation
            )
        )
    execute.assert_not_awaited()
    assert result.outcome == "blocked" and result.attempt_id is not None
    page = await AgentTriggerService(db).attempts(
        ctx, trigger.agent_id, trigger.id, skip=0, limit=50
    )
    assert len(page.items) == 1
    assert (page.items[0].reason, page.items[0].stage) == (
        "platform_identity_required",
        "source_review",
    )
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0


@pytest.mark.parametrize(
    "expected",
    [
        "source_review_required",
        "platform_identity_required",
        "preparation_failed",
        "agent_unavailable",
    ],
)
async def test_preparation_failure_survives_rollback_and_has_no_raw_error(
    db: AsyncSession, expected: str
) -> None:
    from app.core.exceptions import BadRequestError

    ctx, trigger, _, _ = await world(db)
    trigger_id, agent_id = trigger.id, trigger.agent_id
    policy_id = read_policy(trigger.approved_sources).id
    activation = uuid4()
    # The worker reads committed admission; its refusal rolls back tentative run rows.
    await db.commit()
    refusal = (
        PlatformRoutineIdentityRequired()
        if expected == "platform_identity_required"
        else RoutineSourcesRequired(message="secret-provider-error")
        if expected == "source_review_required"
        else BadRequestError(message="secret-provider-error")
        if expected == "agent_unavailable"
        else RuntimeError("secret-provider-error")
    )
    with patch(
        "app.services.agent_runner.AgentRunnerService.execute", AsyncMock(side_effect=refusal)
    ):
        result = await AgentTriggerService(db).fire_job(
            FireTrigger(trigger_id=trigger_id, source_policy_id=policy_id, activation_id=activation)
        )
    assert result.outcome == ("failed" if expected == "preparation_failed" else "blocked")
    page = await AgentTriggerService(db).attempts(ctx, agent_id, trigger_id, skip=0, limit=50)
    assert len(page.items) == 1 and page.items[0].reason == expected
    assert "secret-provider-error" not in page.model_dump_json()
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0


@pytest.mark.security
@pytest.mark.parametrize("policy", ["invalid", "stale"])
@pytest.mark.parametrize("claimed", [False, True])
async def test_admission_refusals_remain_in_attempt_history(
    db: AsyncSession, policy: str, claimed: bool
) -> None:
    from datetime import UTC, datetime

    from app.db.models.background_job import BackgroundJob

    ctx, trigger, _, _ = await world(db)
    activation = uuid4()
    ticket = datetime.now(UTC) if claimed else None
    trigger.fire_in_flight_since = ticket
    if policy == "invalid":
        trigger.approved_sources = {}
    await db.flush()
    service = AgentTriggerService(db)
    with patch("app.services.notifications.NotificationService.routine_blocked", AsyncMock()):
        queued = await service.queue_fire(
            trigger.id,
            organization_id=ctx.organization_id,
            activation_id=activation,
            claimed_at=ticket,
            source_policy_id=uuid4() if policy == "stale" else None,
        )
    assert queued is None
    attempts = await service.attempts(ctx, trigger.agent_id, trigger.id, skip=0, limit=10)
    assert [(item.activation_id, item.reason) for item in attempts.items] == [
        (activation, "source_review_required")
    ]
    await db.refresh(trigger)
    assert trigger.fire_in_flight_since is None
    assert await db.scalar(select(func.count()).select_from(BackgroundJob)) == 0
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0


@pytest.mark.security
@pytest.mark.parametrize("foreign", [False, True])
async def test_missing_or_foreign_admissions_do_not_record_attempts(
    db: AsyncSession, foreign: bool
) -> None:
    from app.core.exceptions import AuthorizationError

    ctx, trigger, _, _ = await world(db)
    trigger.approved_sources = {}
    await db.flush()
    service = AgentTriggerService(db)
    if foreign:
        with pytest.raises(AuthorizationError):
            await service.queue_fire(trigger.id, organization_id=uuid4())
    else:
        assert await service.queue_fire(uuid4(), organization_id=ctx.organization_id) is None
    assert (await service.attempts(ctx, trigger.agent_id, trigger.id, skip=0, limit=10)).total == 0
