"""Tests for the embed repository's departure pause.

The pause is the statement, so this reads the statement back rather than
counting calls: a dropped `organization_id` filter would pause another
organization's widgets, and a missing `owner_user_id` filter would pause
everyone's. A paused embed refuses admission everywhere it is checked, so
the pause is what stops a departed publisher's surfaces answering as them.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories import agent_embed_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    async def flush(self) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    """The values the last statement actually filters on."""
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


class TestPausingOnDeparture:
    async def test_leaving_pauses_only_that_members_active_embeds_in_the_org(self):
        """The departure pause is one UPDATE: the leaver's active embeds in this
        organization, and nothing else - another member's embeds, another
        organization's, and ones already paused keep answering."""
        organization_id, user_id = uuid.uuid4(), uuid.uuid4()
        session = _RecordingSession(MagicMock(rowcount=3))

        paused = await agent_embed_repo.pause_for_owner(
            session, organization_id=organization_id, user_id=user_id
        )

        assert paused == 3
        statement = session.statements[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert sql.startswith("UPDATE agent_embeds SET is_active=")
        params = _filters(session)
        assert organization_id in params.values()
        assert user_id in params.values()
        assert False in params.values()
