"""Mutation reads refresh the identity map without blocking new run foreign keys."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.agent import Agent
from app.repositories import agent_repo

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("locked", [False, True])
async def test_agent_mutation_lock_is_tenant_scoped_and_allows_key_share(locked: bool) -> None:
    organization = uuid4()
    row = Agent(id=uuid4(), organization_id=organization, name="Support", slug="support")
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = MagicMock(execute=AsyncMock(return_value=result))
    assert await agent_repo.get(db, row.id, organization_id=organization, for_update=locked) is row
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert ("FOR NO KEY UPDATE" in sql) is locked
    assert "agents.organization_id =" in sql and "agents.id =" in sql
    assert statement.get_execution_options().get("populate_existing", False) is locked
