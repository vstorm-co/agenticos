"""Which surface each entry point stamps on the run it opens.

`agent_runs.surface` answers "where did this come from", and it failed in both
directions at once. `PLAYGROUND` is still unassigned and absent - nothing runs an
agent in a playground yet - so a filter offering it would answer with nothing on
every deployment for ever (#207); `SCHEDULE` was the same until agenticos#44 gave
it a writer, the trigger heartbeat. And `EMBED` did not exist, so an embedded
widget's run was stamped `WEB` while a Mattermost mention fell through a `.get`
default and was recorded as an HTTP API call (#208).

Both are silent: nothing errors, the number lands in the wrong bucket, and every
reader of the column inherits it. Which is why this file asserts the *recorded
value* per entry point rather than that a call was made - the code paths were
already exercised by other tests, and none of them looked at what was written.
"""

from __future__ import annotations

import uuid
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

    def test_the_vocabulary_is_exactly_the_seven_surfaces_that_exist(self):
        assert {surface.value for surface in RunSurface} == {
            "web",
            "embed",
            "api",
            "slack",
            "telegram",
            "mattermost",
            "schedule",
        }

    def test_playground_is_absent_but_schedule_now_has_a_writer(self):
        """`playground` stays gone - nothing runs an agent in one, so a filter
        offering it would answer with nothing, always. `schedule` is the opposite
        case now: agenticos#44's heartbeat stamps every run it fires, so the
        member earns its place (that it is written is proven in
        `tests/test_agent_triggers.py`)."""
        assert not hasattr(RunSurface, "PLAYGROUND")
        assert RunSurface.SCHEDULE.value == "schedule"

    def test_every_channel_this_router_serves_is_in_the_surface_map(self):
        """The map's `.get(platform, API)` default is what silently recorded a
        Mattermost mention as an HTTP API call. A platform missing here does not
        error; it lands in the wrong bucket."""
        assert set(_SURFACES) == {"slack", "telegram", "mattermost"}
        assert _SURFACES["mattermost"] is RunSurface.MATTERMOST


class TestWhatTheEmbeddedWidgetStamps:
    @staticmethod
    def _session(runner: MagicMock) -> Any:
        from app.services.embed_session import EmbedSession

        session = EmbedSession.__new__(EmbedSession)
        session.db = MagicMock()
        session.runner = runner
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
        session._context_sent = False
        return session

    async def test_an_embedded_run_is_recorded_as_embed_and_not_as_web_chat(self):
        """A widget on somebody else's public site and an employee in the
        dashboard are not the same thing to anybody asking how the product is
        used. Stamped `web`, an embedded run was indistinguishable from one."""
        runner = MagicMock(execute=AsyncMock(return_value=("the answer", MagicMock())))
        session = self._session(runner)

        with patch("app.services.embed_session.member_repo") as members:
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
        session.db = MagicMock()
        session.runner = runner
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
        session._context_sent = False
        session._supplied = {}
        session._supplied_sent = ""
        return session

    async def test_a_value_that_arrives_after_turn_one_still_reaches_the_agent(self):
        runner = MagicMock(execute=AsyncMock(return_value=("ok", MagicMock())))
        session = self._session(runner)

        with patch("app.services.embed_session.member_repo") as members:
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
