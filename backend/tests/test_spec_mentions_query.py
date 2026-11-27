"""The first pass over specs for a page of resource ids walks each stored spec once.

A listing asks about up to a page of ids at a time, and a draft can be large. One
substring match per id meant one scan of a spec's whole text per id, for every
agent, on every list read.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories import agent_environment_repo, agent_repo

pytestmark = [pytest.mark.anyio, pytest.mark.security]

IDS = [str(uuid4()) for _ in range(100)]


def _db() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.tuples.return_value.all.return_value = []
    db.execute.return_value = result
    return db


def _sql(db: AsyncMock) -> str:
    statement = db.execute.await_args.args[0]
    return str(statement.compile(dialect=postgresql.dialect()))


async def test_drafts_are_matched_against_every_id_in_one_walk():
    db = _db()

    await agent_repo.drafts_mentioning(db, IDS, organization_id=uuid4())

    sql = _sql(db)
    assert sql.count("jsonb_path_exists") == 1
    assert "LIKE" not in sql.upper()


async def test_served_specs_are_matched_against_every_id_in_one_walk():
    db = _db()

    await agent_environment_repo.served_mentioning(db, IDS, organization_id=uuid4())

    sql = _sql(db)
    assert sql.count("jsonb_path_exists") == 1
    assert "LIKE" not in sql.upper()
