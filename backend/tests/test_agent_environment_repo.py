"""Tests for the environment repository - the table behind "which version answers where".

Same discipline as the exposure repository's tests: a repository's behaviour
*is* the statement it builds, so these read the statement back. The predicates
are the point - a dropped `organization_id` is a cross-tenant read, and a
default lookup that forgot `is_default` would resolve a random environment.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.agent_environment import AgentEnvironment
from app.repositories import agent_environment_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[AgentEnvironment] = []
        self.deleted: list[AgentEnvironment] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: AgentEnvironment) -> None:
        self.added.append(instance)

    async def delete(self, instance: AgentEnvironment) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: AgentEnvironment) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list[object]):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=values))))


class TestReading:
    async def test_one_environment_is_read_inside_its_organization(self):
        """Without the scope, an environment id from another tenant would resolve."""
        environment_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_environment_repo.get(session, environment_id, organization_id=organization_id)

        assert set(_filters(session).values()) >= {environment_id, organization_id}

    async def test_a_listing_is_scoped_and_puts_the_default_first(self):
        """The Builder renders the default as the row everything is compared
        against, so the order is part of the contract, not styling."""
        agent_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_environment_repo.list_for_agent(
            session, agent_id=agent_id, organization_id=organization_id
        )

        assert set(_filters(session).values()) >= {agent_id, organization_id}
        statement = str(session.statements[-1])
        assert "ORDER BY" in statement
        assert "is_default" in statement

    async def test_the_default_lookup_asks_for_the_default_and_nothing_else(self):
        """A missing `is_default` predicate would resolve whichever row came
        first - a dev environment answering for production."""
        agent_id = uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_environment_repo.get_default_for_agent(session, agent_id=agent_id)

        assert agent_id in _filters(session).values()
        assert "is_default" in str(session.statements[-1])

    async def test_a_name_is_looked_up_on_one_agent_only(self):
        """Names are unique per agent, not per organization - two agents may
        both have a `dev`."""
        agent_id = uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_environment_repo.get_by_name(session, agent_id=agent_id, name="dev")

        assert set(_filters(session).values()) >= {agent_id, "dev"}


class TestWriting:
    async def test_a_new_environment_carries_everything_the_row_needs(self):
        organization_id, agent_id, version_id, author = (uuid.uuid4() for _ in range(4))
        session = _RecordingSession()

        environment = await agent_environment_repo.create(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            name="dev",
            version_id=version_id,
            is_default=True,
            created_by_user_id=author,
        )

        assert session.added == [environment]
        assert (
            environment.organization_id,
            environment.agent_id,
            environment.name,
            environment.version_id,
            environment.is_default,
            environment.created_by_user_id,
        ) == (organization_id, agent_id, "dev", version_id, True, author)

    async def test_promotion_changes_only_the_pointer(self):
        environment = AgentEnvironment(name="production", is_default=True)
        new_version = uuid.uuid4()
        session = _RecordingSession()

        updated = await agent_environment_repo.update(
            session, environment=environment, update_data={"version_id": new_version}
        )

        assert updated.version_id == new_version
        assert (updated.name, updated.is_default) == ("production", True)

    async def test_removing_an_environment_deletes_the_row(self):
        environment = AgentEnvironment(name="dev")
        session = _RecordingSession()

        await agent_environment_repo.delete(session, environment=environment)

        assert session.deleted == [environment]

    def test_an_environment_says_what_it_is_when_printed(self):
        environment = AgentEnvironment(
            id=uuid.uuid4(), agent_id=uuid.uuid4(), name="dev", is_default=False
        )

        assert "dev" in repr(environment)
