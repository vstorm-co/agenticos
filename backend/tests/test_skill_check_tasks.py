"""The worker carries a skill check on: one job per settled run, and a sweep for the rest."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import skill_check_repo
from app.services.skill_check import SkillCheckService
from app.worker.jobs import AdvanceSkillCheck
from app.worker.tasks import skill_check_tasks

pytestmark = pytest.mark.anyio


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    db = MagicMock()

    @asynccontextmanager
    async def context():
        yield db

    monkeypatch.setattr(skill_check_tasks, "get_worker_db_context", context)
    return db


async def test_a_job_advances_its_check(session, monkeypatch) -> None:
    advance = AsyncMock()
    monkeypatch.setattr(SkillCheckService, "advance", advance)
    job = AdvanceSkillCheck(check_id=uuid.uuid4(), organization_id=uuid.uuid4())

    await skill_check_tasks.advance_skill_check(job)

    advance.assert_awaited_once_with(job.check_id, job.organization_id)


async def test_the_sweep_says_how_many_checks_it_looked_at(session, monkeypatch) -> None:
    monkeypatch.setattr(skill_check_repo, "running", AsyncMock(return_value=[]))

    assert await skill_check_tasks.sweep_skill_checks() == 0


async def test_empty_lookups_ask_the_database_nothing(session) -> None:
    db = AsyncMock()

    assert await skill_check_repo.list_agents(db, [], organization_id=uuid.uuid4()) == []
    assert (
        await skill_check_repo.checked_versions(
            db, organization_id=uuid.uuid4(), skill_id=uuid.uuid4(), agent_ids=[]
        )
        == []
    )
    db.execute.assert_not_called()
