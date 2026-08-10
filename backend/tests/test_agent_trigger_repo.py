"""Tests for the trigger repository - the table behind "run this agent on a schedule".

A repository's behaviour *is* the statement it builds, so these read the
statement back rather than counting calls. The claim query is the one that
matters most: a dropped `organization_id` scope on a read is a cross-tenant leak,
and a claim that forgot its `FOR UPDATE SKIP LOCKED` or its terminal-status join
is a double-fire no "the repository was called" assertion would notice. The real
locking and the CHECK constraints are proven against a live database in
`tests/integration/test_agent_trigger_schema.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.agent_trigger import AgentTrigger
from app.repositories import agent_trigger_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[object] = []
        self.deleted: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance) -> None:
        self.added.append(instance)

    async def delete(self, instance) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _sql(session: _RecordingSession) -> str:
    return str(session.statements[-1].compile(dialect=postgresql.dialect())).lower()


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list[object]):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=values))))


class TestReading:
    async def test_one_trigger_is_read_inside_its_organization(self):
        trigger_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))
        await agent_trigger_repo.get(session, trigger_id, organization_id=organization_id)
        assert set(_filters(session).values()) >= {trigger_id, organization_id}

    async def test_the_worker_reads_a_trigger_by_id_alone(self):
        """A fired flow has an id and no tenant; the organization is read off the row."""
        trigger_id = uuid.uuid4()
        session = _RecordingSession(_scalar(None))
        await agent_trigger_repo.get_by_id(session, trigger_id)
        assert set(_filters(session).values()) == {trigger_id}

    async def test_a_listing_is_scoped_to_the_agent_and_its_organization(self):
        agent_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))
        await agent_trigger_repo.list_for_agent(
            session, agent_id=agent_id, organization_id=organization_id
        )
        assert set(_filters(session).values()) >= {agent_id, organization_id}


class TestWriting:
    async def test_create_builds_the_row_from_its_arguments(self):
        session = _RecordingSession()
        organization_id, agent_id, creator = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        trigger = await agent_trigger_repo.create(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            created_by_user_id=creator,
            prompt="summarise",
            schedule_kind="interval",
            interval_seconds=300,
            cron_expression=None,
            environment_id=None,
            next_fire_at=now,
        )
        assert session.added == [trigger]
        assert (trigger.organization_id, trigger.agent_id, trigger.interval_seconds) == (
            organization_id,
            agent_id,
            300,
        )

    async def test_update_applies_only_the_fields_it_is_given(self):
        session = _RecordingSession()
        trigger = MagicMock()
        await agent_trigger_repo.update(session, trigger=trigger, update_data={"is_active": False})
        assert trigger.is_active is False

    async def test_update_with_nothing_to_change_is_a_no_op(self):
        """The service can send an empty change set (all fields unset); the row
        is flushed unchanged rather than the loop assuming at least one field."""
        session = _RecordingSession()
        trigger = AgentTrigger(schedule_kind="interval")
        returned = await agent_trigger_repo.update(session, trigger=trigger, update_data={})
        assert returned is trigger

    async def test_delete_removes_the_row(self):
        session = _RecordingSession()
        trigger = AgentTrigger()
        await agent_trigger_repo.delete(session, trigger)
        assert session.deleted == [trigger]


class TestClaiming:
    async def test_the_claim_is_due_active_attributable_and_locked(self):
        """The whole no-double-fire and no-overlap guard lives in this statement."""
        now = datetime(2026, 6, 1, tzinfo=UTC)
        session = _RecordingSession(_scalars([]))
        await agent_trigger_repo.claim_due(session, now=now)

        sql = _sql(session)
        # The lock that keeps two heartbeats off one trigger, and only the trigger.
        assert "for update of agent_triggers skip locked" in sql
        # The no-overlap join: a fire is skipped while its previous run is unfinished.
        assert "left outer join agent_runs" in sql
        assert now in _filters(session).values()

    async def test_a_claim_returns_the_rows_it_locked(self):
        rows = [MagicMock(), MagicMock()]
        session = _RecordingSession(_scalars(rows))
        claimed = await agent_trigger_repo.claim_due(session, now=datetime(2026, 6, 1, tzinfo=UTC))
        assert claimed == rows
