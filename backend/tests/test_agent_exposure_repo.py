"""Tests for the exposure repository - the table behind "where is this available".

A repository's behaviour *is* the statement it builds, so these read the
statement back rather than counting calls. The predicate is the whole point
here: a dropped `organization_id` filter is a cross-tenant read that no
assertion about "the repository was called" would notice, and a binding lookup
that forgot the bot would restore the hole the table was added to close.

What the schema guarantees on top of this - one binding per agent per bot, only
the surfaces something serves, cascades from both sides - is asserted against a
real database in `tests/integration/test_schema_guarantees.py`.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.agent_exposure import AgentExposure
from app.repositories import agent_exposure_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

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

        By agent alone, any bot in the organization reaches it - the original
        behaviour. By bot alone, every agent it serves answers every handle.
        """
        agent_id, bot_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(_scalar(None))

        await agent_exposure_repo.get_for_bot(session, agent_id=agent_id, channel_bot_id=bot_id)

        assert set(_filters(session).values()) >= {agent_id, bot_id}

    async def test_surfaces_are_grouped_per_agent_and_only_active_ones_count(self):
        """The gallery's channel badges: one grouped query, paused rows excluded.

        The is_active predicate is the behaviour - a card saying "Slack" about
        an agent that stopped answering there is worse than no badge.
        """
        organization_id = uuid.uuid4()
        chatty, quiet = uuid.uuid4(), uuid.uuid4()
        rows = MagicMock(all=MagicMock(return_value=[(chatty, "slack"), (chatty, "telegram")]))
        session = _RecordingSession(rows)

        surfaces = await agent_exposure_repo.active_surfaces_for_agents(
            session, organization_id=organization_id, agent_ids=[chatty, quiet]
        )

        assert surfaces == {chatty: ["slack", "telegram"]}
        assert organization_id in _filters(session).values()
        # The statement itself must carry the is_active predicate - dropping it
        # would put paused channels back on every card.
        assert "is_active" in str(session.statements[-1])

    async def test_no_agents_asks_the_database_nothing(self):
        """An empty page must not issue a grouped query over nothing."""
        session = _RecordingSession()

        surfaces = await agent_exposure_repo.active_surfaces_for_agents(
            session, organization_id=uuid.uuid4(), agent_ids=[]
        )

        assert surfaces == {}
        assert session.statements == []

    async def test_the_agents_a_bot_serves_come_back_with_their_bindings(self):
        """The unaddressed path needs both halves in one read.

        The binding is what bounds the run and the agent row is what names it
        to the sender - and the is_active predicate must live in the statement,
        or a paused binding would put a bot back to answering.
        """
        bot_id = uuid.uuid4()
        exposure, agent = MagicMock(), MagicMock()
        rows = MagicMock(all=MagicMock(return_value=[(exposure, agent)]))
        session = _RecordingSession(rows)

        pairs = await agent_exposure_repo.list_active_for_bot(session, channel_bot_id=bot_id)

        assert pairs == [(exposure, agent)]
        assert bot_id in _filters(session).values()
        statement = str(session.statements[-1])
        assert "is_active" in statement
        assert "JOIN agents" in statement

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
        for its environment too, and whatever the caller defaulted to would
        overwrite what somebody else set.
        """
        environment_id = uuid.uuid4()
        exposure = AgentExposure(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            surface="slack",
            channel_bot_id=uuid.uuid4(),
            environment_id=environment_id,
        )
        session = _RecordingSession()

        updated = await agent_exposure_repo.update(
            session, exposure=exposure, update_data={"is_active": False}
        )

        assert (updated.is_active, updated.environment_id) == (False, environment_id)

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
