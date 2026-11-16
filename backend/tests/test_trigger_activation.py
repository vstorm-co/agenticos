"""An exact queued fire's receipt never depends on the visible history page."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.background_job import BackgroundJob, JobStatus
from app.db.models.routine_device_wait import RoutineDeviceWait
from app.repositories import agent_run_repo, agent_trigger_repo
from app.repositories import background_job as job_repo
from app.repositories import routine_device_wait as wait_repo
from app.services.agent_trigger import AgentTriggerService

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def no_device_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait_repo, "get", AsyncMock(return_value=None))


@pytest.mark.parametrize(
    "status,expected",
    [
        ("queued", "pending"),
        ("running", "pending"),
        ("succeeded", "not_started"),
        ("dead", "not_started"),
        ("cancelled", "not_started"),
    ],
)
async def test_job_settlement_covers_a_fire_that_never_started(
    monkeypatch: pytest.MonkeyPatch,
    status: JobStatus,
    expected: str,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    trigger = AgentTrigger(
        id=uuid4(), agent_id=uuid4(), organization_id=ctx.organization_id, is_active=False
    )
    activation_id, job_id = uuid4(), uuid4()
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_owned", AsyncMock(return_value=trigger))
    monkeypatch.setattr(
        agent_run_repo, "run_id_for_routine_activation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(agent_trigger_repo, "attempt_for_activation", AsyncMock(return_value=None))
    monkeypatch.setattr(
        job_repo,
        "get",
        AsyncMock(
            return_value=BackgroundJob(
                id=job_id,
                organization_id=ctx.organization_id,
                kind="fire-trigger",
                status=status,
                payload={"trigger_id": str(trigger.id), "activation_id": str(activation_id)},
            )
        ),
    )
    result = await service.activation_status(
        ctx, trigger.agent_id, trigger.id, activation_id, job_id
    )
    assert result.state == expected


@pytest.mark.parametrize(
    "run_exists,attempt_exists", [(True, False), (False, True), (False, False)]
)
async def test_recorded_outputs_survive_job_retention(
    monkeypatch: pytest.MonkeyPatch,
    run_exists: bool,
    attempt_exists: bool,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    trigger = AgentTrigger(id=uuid4(), agent_id=uuid4(), organization_id=ctx.organization_id)
    activation_id = uuid4()
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_owned", AsyncMock(return_value=trigger))
    lookup = AsyncMock(return_value=uuid4() if run_exists else None)
    monkeypatch.setattr(agent_run_repo, "run_id_for_routine_activation", lookup)
    monkeypatch.setattr(
        agent_trigger_repo,
        "attempt_for_activation",
        AsyncMock(return_value=object() if attempt_exists else None),
    )
    monkeypatch.setattr(job_repo, "get", AsyncMock(return_value=None))
    if run_exists or attempt_exists:
        assert (
            await service.activation_status(ctx, trigger.agent_id, trigger.id, activation_id, None)
        ).state == "recorded"
    else:
        with pytest.raises(NotFoundError):
            await service.activation_status(
                ctx, trigger.agent_id, trigger.id, activation_id, uuid4()
            )
    lookup.assert_awaited_once_with(
        db, organization_id=ctx.organization_id, trigger_id=trigger.id, activation_id=activation_id
    )


@pytest.mark.security
@pytest.mark.parametrize("wrong", ["organization_id", "kind", "trigger_id", "activation_id"])
async def test_another_tenants_or_activations_job_is_not_a_receipt(
    monkeypatch: pytest.MonkeyPatch,
    wrong: str,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    trigger = AgentTrigger(id=uuid4(), agent_id=uuid4(), organization_id=ctx.organization_id)
    activation_id = uuid4()
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_owned", AsyncMock(return_value=trigger))
    job = BackgroundJob(
        id=uuid4(),
        organization_id=ctx.organization_id,
        kind="fire-trigger",
        status="succeeded",
        payload={"trigger_id": str(trigger.id), "activation_id": str(activation_id)},
    )
    if wrong == "organization_id":
        job.organization_id = uuid4()
    elif wrong == "kind":
        job.kind = "other"
    else:
        job.payload[wrong] = str(uuid4())
    monkeypatch.setattr(job_repo, "get", AsyncMock(return_value=job))
    with pytest.raises(NotFoundError):
        await service.activation_status(ctx, trigger.agent_id, trigger.id, activation_id, job.id)


async def test_activation_lookup_has_no_history_count_or_page() -> None:
    db = AsyncMock(spec=AsyncSession)
    run_id = uuid4()
    db.scalar.return_value = run_id
    assert (
        await agent_run_repo.run_id_for_routine_activation(
            db, organization_id=uuid4(), trigger_id=uuid4(), activation_id=uuid4()
        )
        == run_id
    )
    statement = db.scalar.await_args.args[0]
    sql = str(statement)
    assert "count(" not in sql.lower()
    assert "OFFSET" not in sql
    assert "->> 'activation_id'" in sql


@pytest.mark.parametrize(
    "status,expected",
    [
        ("waiting", "pending"),
        ("started", "recorded"),
        ("cancelled", "not_started"),
        ("expired", "not_started"),
        ("failed", "not_started"),
    ],
)
async def test_device_activation_outlives_its_first_job(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: str,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    trigger = AgentTrigger(id=uuid4(), agent_id=uuid4(), organization_id=ctx.organization_id)
    activation_id = uuid4()
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_owned", AsyncMock(return_value=trigger))
    monkeypatch.setattr(
        agent_run_repo, "run_id_for_routine_activation", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(agent_trigger_repo, "attempt_for_activation", AsyncMock(return_value=None))
    job = BackgroundJob(
        id=uuid4(),
        organization_id=ctx.organization_id,
        kind="fire-trigger",
        status="succeeded",
        payload={"trigger_id": str(trigger.id), "activation_id": str(activation_id)},
    )
    monkeypatch.setattr(job_repo, "get", AsyncMock(return_value=job))
    monkeypatch.setattr(
        wait_repo,
        "get",
        AsyncMock(
            return_value=RoutineDeviceWait(
                id=activation_id,
                organization_id=ctx.organization_id,
                trigger_id=trigger.id,
                status=status,
            )
        ),
    )
    assert (
        await service.activation_status(ctx, trigger.agent_id, trigger.id, activation_id, job.id)
    ).state == expected


@pytest.mark.security
@pytest.mark.parametrize("wrong_org", [False, True])
async def test_another_routines_device_wait_is_not_a_receipt(
    monkeypatch: pytest.MonkeyPatch, wrong_org: bool
) -> None:
    db = AsyncMock(spec=AsyncSession)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    trigger = AgentTrigger(id=uuid4(), agent_id=uuid4(), organization_id=ctx.organization_id)
    activation_id = uuid4()
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_owned", AsyncMock(return_value=trigger))
    monkeypatch.setattr(
        wait_repo,
        "get",
        AsyncMock(
            return_value=RoutineDeviceWait(
                id=activation_id,
                organization_id=uuid4() if wrong_org else ctx.organization_id,
                trigger_id=trigger.id if wrong_org else uuid4(),
                status="waiting",
            )
        ),
    )
    with pytest.raises(NotFoundError):
        await service.activation_status(ctx, trigger.agent_id, trigger.id, activation_id, None)
