"""The suite runs against a database of its own, not a shared one.

`tests/test_integration_database_isolation.py` checks the name and the guard
without a database. This checks the consequence: that the fixture created the
database that name refers to and the session is connected to it. If the fixture
ever fell back to a shared name, every other test here would still pass while
two concurrent runs dropped each other's tables again (#189).
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.anyio


class TestTheDatabaseTheSuiteConnectsTo:
    async def test_it_belongs_to_this_pytest_process_alone(self, db: AsyncSession) -> None:
        connected_to = (await db.execute(text("SELECT current_database()"))).scalar_one()
        assert connected_to == os.environ["POSTGRES_DB"]
        assert connected_to.endswith(f"_p{os.getpid()}")


class TestTheScratchDatabaseOfADdlTest:
    async def test_schema_changes_there_never_reach_the_workers_database(
        self, engine: AsyncEngine, scratch_engine: AsyncEngine
    ) -> None:
        """A migration test downgrading the shared database broke every later test (#238)."""
        async with scratch_engine.begin() as connection:
            scratch_name = (
                await connection.execute(text("SELECT current_database()"))
            ).scalar_one()
            await connection.execute(
                text("ALTER TABLE skill_proposals RENAME TO skill_proposals_moved")
            )
        async with engine.connect() as connection:
            shared_name = (await connection.execute(text("SELECT current_database()"))).scalar_one()
            shared_has_table = await connection.scalar(
                text("SELECT to_regclass('skill_proposals')")
            )
        assert shared_name == os.environ["POSTGRES_DB"] != scratch_name
        assert scratch_name.startswith(f"{shared_name}_s")
        assert shared_has_table is not None
