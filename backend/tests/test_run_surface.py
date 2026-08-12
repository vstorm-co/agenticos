"""Which surface each entry point stamps on the run it opens.

`agent_runs.surface` answers "where did this come from", and it failed in both
directions at once. Two members were never assigned - `PLAYGROUND` and `SCHEDULE`
- so anything enumerating the vocabulary offered filters that answer with nothing
on every deployment for ever (#207). And `EMBED` did not exist, so an embedded
widget's run was stamped `WEB` while a Mattermost mention fell through a `.get`
default and was recorded as an HTTP API call (#208).

Both are silent: nothing errors, the number lands in the wrong bucket, and every
reader of the column inherits it. Which is why this file asserts the *recorded
value* per entry point rather than that a call was made - the code paths were
already exercised by other tests, and none of them looked at what was written.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.agent_run import RunSurface
from app.services.channels.mentions import _SURFACES

pytestmark = pytest.mark.anyio


class TestEveryMemberIsAssignedBySomething:
    """The rule the enum's docstring states, asserted rather than trusted.

    A value with no writer is a filter that lies, and the last two cost two
    design documents a paragraph each explaining the omission.
    """

    def test_the_vocabulary_is_exactly_the_six_surfaces_that_exist(self):
        assert {surface.value for surface in RunSurface} == {
            "web",
            "embed",
            "api",
            "slack",
            "telegram",
            "mattermost",
        }

    def test_nothing_names_a_surface_that_was_deleted(self):
        """`playground` and `schedule` are gone. A filter offering either would
        answer with nothing, always - and a reader would conclude that scheduled
        runs exist and none have happened yet."""
        assert not hasattr(RunSurface, "PLAYGROUND")
        assert not hasattr(RunSurface, "SCHEDULE")

    def test_every_channel_this_router_serves_is_in_the_surface_map(self):
        """The map's `.get(platform, API)` default is what silently recorded a
        Mattermost mention as an HTTP API call. A platform missing here does not
        error; it lands in the wrong bucket."""
        assert set(_SURFACES) == {"slack", "telegram", "mattermost"}
        assert _SURFACES["mattermost"] is RunSurface.MATTERMOST


def _one_session() -> Any:
    """A session factory for a test that builds its session with `__new__`.

    `EmbedSession` opens one per turn rather than holding the socket's own, so
    the attribute these tests set is the factory and not a session (#39).
    """

    @asynccontextmanager
    async def factory() -> Any:
        yield MagicMock()

    return factory


@contextmanager
def _a_turn(runner: MagicMock) -> Any:
    """The turn's runner and the rows it reads, mocked at the repository."""
    with (
        patch("app.services.embed_session.AgentRunnerService", return_value=runner),
        patch("app.services.embed_session.conversation_repo") as conversations,
        patch("app.services.embed_session.member_repo") as members,
    ):
        conversations.count_messages = AsyncMock(return_value=0)
        conversations.get_messages_by_conversation = AsyncMock(return_value=[])
        yield members


class TestWhatTheEmbeddedWidgetStamps:
    @staticmethod
    def _session(runner: MagicMock) -> Any:
        from app.services.embed_session import EmbedSession

        session = EmbedSession.__new__(EmbedSession)
        session.sessions = _one_session()
        session.embed = MagicMock(
            id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            owner_user_id=None,
            name="Support",
            context=None,
        )
        session.conversation_id = uuid.uuid4()
        session.visitor = "visitor-1"
        session.hosted = False
        session.visitor_key = None
        session._context_sent = False
        return session

    async def test_an_embedded_run_is_recorded_as_embed_and_not_as_web_chat(self):
        """A widget on somebody else's public site and an employee in the
        dashboard are not the same thing to anybody asking how the product is
        used. Stamped `web`, an embedded run was indistinguishable from one."""
        runner = MagicMock(execute=AsyncMock(return_value=("the answer", MagicMock())))
        session = self._session(runner)

        with _a_turn(runner) as members:
            members.get = AsyncMock(return_value=None)
            await session._answer("how do I get a refund?")

        assert runner.execute.await_args.kwargs["surface"] is RunSurface.EMBED


class TestTheSuppliedContextIsResentWhenItChanges:
    """A single-page app signs a visitor in on turn 2, so the block the page
    supplies has to reach the agent then - not stay frozen at what turn 1 held.
    Latching the whole preamble on the first turn froze the supplied block, and
    its `required`-variable warning, at whatever turn 1 happened to carry.
    """

    @staticmethod
    def _session(runner: MagicMock) -> Any:
        from app.services.embed_session import EmbedSession

        session = EmbedSession.__new__(EmbedSession)
        session.sessions = _one_session()
        session.embed = MagicMock(
            id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            owner_user_id=None,
            name="Support",
            context="A billing widget",
            context_variables=[{"name": "email", "required": True}],
        )
        session.conversation_id = uuid.uuid4()
        session.visitor = "visitor-1"
        session.hosted = False
        session.visitor_key = None
        session._context_sent = False
        session._supplied = {}
        session._supplied_sent = ""
        return session

    async def test_a_value_that_arrives_after_turn_one_still_reaches_the_agent(self):
        runner = MagicMock(execute=AsyncMock(return_value=("ok", MagicMock())))
        session = self._session(runner)

        with _a_turn(runner) as members:
            members.get = AsyncMock(return_value=None)

            # Turn 1: not signed in. The placement context goes; the required
            # `email` is missing, so the supplied block is empty.
            await session._answer("hi")
            first = runner.execute.await_args.args[2]

            # Turn 2: the page now knows the visitor's email.
            session._supplied = {"email": "a@b.com"}
            await session._answer("now")
            second = runner.execute.await_args.args[2]

        assert "A billing widget" in first
        assert "a@b.com" not in first
        # The value that only arrived on turn 2 must be sent, and the placement
        # context must not be repeated now it has already gone.
        assert "a@b.com" in second
        assert "A billing widget" not in second
