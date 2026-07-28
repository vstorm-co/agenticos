"""Tests for the exposure repository — the table behind "where is this available".

A repository's behaviour *is* the statement it builds, so these read the
statement back rather than counting calls. The predicate is the whole point
here: a dropped ``organization_id`` filter is a cross-tenant read that no
assertion about "the repository was called" would notice, and a binding lookup
that forgot the bot would restore the hole the table was added to close.

What the schema guarantees on top of this — one binding per agent per bot, only
the surfaces something serves, cascades from both sides — is asserted against a
real database in ``tests/integration/test_schema_guarantees.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.agent_exposure import AgentExposure
from app.repositories import agent_exposure_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An ``AsyncSession`` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[AgentExposure] = []
        self.deleted: list[AgentExposure] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: AgentExposure) -> None:
        self.added.append(instance)

    async def delete(self, instance: AgentExposure) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: AgentExposure) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    """The values the last statement actually filters on."""
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _scalars(values: list[object]):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=values))))


class TestReading:
    async def test_one_exposure_is_read_inside_its_organization(self):
        """Without the scope, an exposure id from another tenant would resolve."""
        exposure_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_exposure_repo.get(session, exposure_id, organization_id=organization_id)

        assert set(_filters(session).values()) >= {exposure_id, organization_id}

    async def test_a_listing_is_scoped_to_the_agent_and_its_organization(self):
        agent_id, organization_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalars([]))

        await agent_exposure_repo.list_for_agent(
            session, agent_id=agent_id, organization_id=organization_id
        )

        assert set(_filters(session).values()) >= {agent_id, organization_id}

    async def test_a_binding_is_looked_up_by_agent_and_bot_together(self):
        """Either half alone is the hole this table exists to close.

        By agent alone, any bot in the organization reaches it — the original
        behaviour. By bot alone, every agent it serves answers every handle.
        """
        agent_id, bot_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_exposure_repo.get_for_bot(session, agent_id=agent_id, channel_bot_id=bot_id)

        assert set(_filters(session).values()) >= {agent_id, bot_id}

    async def test_a_paused_binding_is_still_returned(self):
        """The duplicate check needs it, and it is the only caller that does.

        Filtering it out here would make a paused binding indistinguishable from
        no binding, and a second insert would then race the unique constraint.
        """
        paused = MagicMock(is_active=False)
        session = _RecordingSession(_scalar(paused))

        found = await agent_exposure_repo.get_for_bot(
            session, agent_id=uuid.uuid4(), channel_bot_id=uuid.uuid4()
        )

        assert found is paused


class TestWriting:
    async def test_a_new_binding_carries_everything_the_row_needs(self):
        organization_id, agent_id, bot_id, author = (uuid.uuid4() for _ in range(4))
        session = _RecordingSession()

        exposure = await agent_exposure_repo.create(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            surface="slack",
            channel_bot_id=bot_id,
            created_by_user_id=author,
        )

        assert session.added == [exposure]
        assert (
            exposure.organization_id,
            exposure.agent_id,
            exposure.surface,
            exposure.channel_bot_id,
            exposure.created_by_user_id,
        ) == (organization_id, agent_id, "slack", bot_id, author)

    @pytest.mark.parametrize("is_active", [True, False])
    async def test_pausing_and_resuming_change_only_the_flag(self, is_active):
        """A binding keeps who made it and when; that is what pausing is for."""
        exposure = AgentExposure(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            surface="slack",
            channel_bot_id=uuid.uuid4(),
            is_active=not is_active,
        )
        session = _RecordingSession()

        updated = await agent_exposure_repo.update(
            session, exposure=exposure, update_data={"is_active": is_active}
        )

        assert updated.is_active is is_active
        assert session.added == [exposure]

    async def test_only_the_fields_that_were_sent_are_written(self):
        """A dict rather than named arguments, so "unsent" is expressible.

        With one keyword per field, pausing a binding would have to pass a value
        for its budget too, and whatever the caller defaulted to would overwrite
        what somebody else set.
        """
        exposure = AgentExposure(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            surface="slack",
            channel_bot_id=uuid.uuid4(),
            monthly_usd=Decimal("25"),
        )
        session = _RecordingSession()

        updated = await agent_exposure_repo.update(
            session, exposure=exposure, update_data={"is_active": False}
        )

        assert (updated.is_active, updated.monthly_usd) == (False, Decimal("25"))

    async def test_a_binding_can_be_created_carrying_its_caps(self):
        session = _RecordingSession()

        exposure = await agent_exposure_repo.create(
            session,
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            surface="slack",
            channel_bot_id=uuid.uuid4(),
            created_by_user_id=None,
            max_per_run_usd=Decimal("0.5"),
            monthly_usd=Decimal("25"),
        )

        assert (exposure.max_per_run_usd, exposure.monthly_usd) == (
            Decimal("0.5"),
            Decimal("25"),
        )

    async def test_removing_a_binding_deletes_the_row(self):
        exposure = AgentExposure(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            surface="slack",
            channel_bot_id=uuid.uuid4(),
        )
        session = _RecordingSession()

        await agent_exposure_repo.delete(session, exposure)

        assert session.deleted == [exposure]


class TestTheRowItself:
    def test_an_exposure_says_what_it_is_when_printed(self):
        """A log line naming a bare uuid is a log line nobody can act on."""
        agent_id = uuid.uuid4()
        exposure = AgentExposure(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            agent_id=agent_id,
            surface="telegram",
            channel_bot_id=uuid.uuid4(),
        )

        assert repr(exposure) == f"<AgentExposure(agent={agent_id}, surface=telegram)>"
