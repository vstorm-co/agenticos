"""The worker's half of the platform's initiative: each job, one session, one call (#2301)."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import jobs
from app.worker.handlers import production
from app.worker.jobs import InstallRolePack, ThinkForPerson, Tick, WelcomeMember
from app.worker.schedules import SCHEDULES
from app.worker.tasks import proactive_tasks

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
USER = uuid.uuid4()


@pytest.fixture
def service():
    proactive = MagicMock(
        sweep=AsyncMock(return_value=2),
        think_for=AsyncMock(return_value=1),
        install_role_pack=AsyncMock(return_value=3),
        welcome=AsyncMock(return_value=1),
    )

    @asynccontextmanager
    async def session():
        yield MagicMock()

    with (
        patch.object(proactive_tasks, "get_db_context", new=session),
        patch.object(proactive_tasks, "ProactiveService", return_value=proactive),
    ):
        yield proactive


async def test_the_sweep_hands_its_tick_to_the_service(service):
    when = datetime(2026, 10, 22, 3, tzinfo=UTC)

    assert await proactive_tasks.proactive_sweep(Tick(scheduled_for=when)) == 2
    service.sweep.assert_awaited_once_with(now=when)

    service.sweep.return_value = 0
    assert await proactive_tasks.proactive_sweep(Tick(scheduled_for=when)) == 0


async def test_each_job_reaches_its_person(service):
    assert (
        await proactive_tasks.think_for_person(ThinkForPerson(organization_id=ORG, user_id=USER))
        == 1
    )
    assert (
        await proactive_tasks.install_role_pack(
            InstallRolePack(organization_id=ORG, user_id=USER, pack_id="sales")
        )
        == 3
    )
    assert (
        await proactive_tasks.welcome_member(WelcomeMember(organization_id=ORG, user_id=USER)) == 1
    )
    service.install_role_pack.assert_awaited_once_with(ORG, USER, "sales")


def test_every_kind_is_bound_and_the_sweep_is_scheduled_hourly():
    handlers = production()
    for task in (
        jobs.THINK_FOR_PERSON,
        jobs.INSTALL_ROLE_PACK,
        jobs.WELCOME_MEMBER,
        jobs.PROACTIVE_SWEEP,
    ):
        assert task.kind in handlers
    [sweep] = [schedule for schedule in SCHEDULES if schedule.task is jobs.PROACTIVE_SWEEP]
    assert sweep.every.total_seconds() == 3600


def test_a_greeting_and_a_model_call_are_never_retried_and_a_pack_is():
    # A retried greeting greets twice; a retried look pays twice; a pack is idempotent.
    assert jobs.WELCOME_MEMBER.max_attempts == 1
    assert jobs.THINK_FOR_PERSON.max_attempts == 1
    assert jobs.INSTALL_ROLE_PACK.max_attempts == 3
    assert jobs.THINK_FOR_PERSON.pool is jobs.Pool.AGENT
