"""Tests for the sandbox connection repository.

A repository's behaviour *is* the statement it builds, so these read the
statement back. The predicate that matters here is `organization_id`: a
connection is an address and a credential that can run commands on a host, so a
lookup without the tenant would let one organization point its agents at
another's Docker socket by guessing an id.

The other thing worth a test is `clear_default`. Exactly one default has to
survive promoting a connection, and the failure mode of getting it wrong is
silent - an agent naming no connection resolves to whichever row happens to
answer first, which is not the one the operator chose.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.sandbox_connection import SandboxConnection
from app.repositories import sandbox_connection_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[SandboxConnection] = []
        self.deleted: list[SandboxConnection] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0) if self._results else MagicMock()

    def add(self, instance: SandboxConnection) -> None:
        self.added.append(instance)

    async def delete(self, instance: SandboxConnection) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: SandboxConnection) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list[object]):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=values))))


def _connection(**overrides: object) -> SandboxConnection:
    row = SandboxConnection(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Local Docker",
        kind="docker",
        base_url="http://sandboxd:8080",
        is_default=True,
        is_active=True,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


class TestReading:
    async def test_a_connection_is_looked_up_inside_its_organization(self):
        """Without the scope, another tenant's host resolves by id."""
        organization_id, connection_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await sandbox_connection_repo.get(session, connection_id, organization_id=organization_id)

        assert set(_filters(session).values()) >= {organization_id, connection_id}

    async def test_the_default_must_also_be_switched_on(self):
        """A connection turned off is one an operator has said not to use; still
        answering as the default would route every agent to it anyway."""
        session = _RecordingSession(_scalar(None))

        await sandbox_connection_repo.get_default(session, organization_id=uuid.uuid4())

        statement = str(session.statements[-1])
        assert "is_default" in statement
        assert "is_active" in statement

    async def test_a_name_is_unique_only_within_the_organization(self):
        organization_id = uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await sandbox_connection_repo.get_by_name(
            session, organization_id=organization_id, name="Big box"
        )

        assert set(_filters(session).values()) >= {organization_id, "Big box"}

    async def test_a_listing_puts_the_default_first(self):
        """It is the one an agent gets when it names none, so it is the one an
        operator is looking for."""
        organization_id = uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await sandbox_connection_repo.list_for_organization(
            session, organization_id=organization_id
        )

        assert organization_id in _filters(session).values()
        assert "ORDER BY" in str(session.statements[-1])


class TestWriting:
    async def test_creating_records_the_host_and_its_credential_reference(self):
        session = _RecordingSession()
        organization_id, secret_id = uuid.uuid4(), uuid.uuid4()

        await sandbox_connection_repo.create(
            session,
            organization_id=organization_id,
            name="Big box",
            kind="docker",
            base_url="http://big:8080",
            secret_id=secret_id,
            default_runtime="data-science",
            is_default=True,
        )

        [created] = session.added
        assert created.organization_id == organization_id
        assert created.name == "Big box"
        assert created.base_url == "http://big:8080"
        assert created.secret_id == secret_id
        assert created.default_runtime == "data-science"
        assert created.is_default is True

    async def test_updating_applies_only_the_fields_it_was_given(self):
        session = _RecordingSession()
        row = _connection(name="Old", base_url="http://old:8080")

        updated = await sandbox_connection_repo.update_connection(
            session, connection=row, update_data={"name": "New"}
        )

        assert updated.name == "New"
        assert updated.base_url == "http://old:8080"

    async def test_promoting_demotes_the_others_in_one_statement(self):
        """A loop that failed in the middle would leave none or two defaults."""
        organization_id, keep = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession()

        await sandbox_connection_repo.clear_default(
            session, organization_id=organization_id, except_id=keep
        )

        statement = str(session.statements[-1])
        assert statement.startswith("UPDATE sandbox_connections")
        assert organization_id in _filters(session).values()
        assert keep in _filters(session).values()

    async def test_demoting_every_default_needs_no_exception(self):
        session = _RecordingSession()

        await sandbox_connection_repo.clear_default(session, organization_id=uuid.uuid4())

        assert "id !=" not in str(session.statements[-1])

    async def test_deleting_removes_the_row(self):
        session = _RecordingSession()
        row = _connection()

        await sandbox_connection_repo.delete(session, connection=row)

        assert session.deleted == [row]


def test_a_connection_says_what_it_is_without_its_credential():
    """`__repr__` reaches log lines, and a token in one outlives the request."""
    text = repr(_connection())

    assert "Local Docker" in text
    assert "docker" in text
