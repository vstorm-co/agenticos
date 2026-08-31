"""Whether a bot's inbound connection is up, where somebody can see it.

A polling bot whose stream never opened looked identical to a working one:
`/channels` showed the row, its `Polling` badge, an agent bound to it and nothing
else, while the reason sat in a `logger.warning` inside the container. "The bot
does not answer" and "the bot is fine" were the same pixels (#1351).

Unknown is a third answer and the tests below are mostly about it. Claiming
healthy is the defect being fixed; claiming broken is the same defect pointing
the other way, and it would put a red badge on every bot in a deployment whose
Redis is not configured.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.channels import connection_state

pytestmark = pytest.mark.anyio


class _Redis:
    """Enough of the client for these: a dict with the three methods used."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> int:
        return int(self.store.pop(key, None) is not None)


@pytest.fixture(autouse=True)
def _clean():
    yield
    connection_state.configure(None)


class TestWhatTheListingLearns:
    async def test_a_started_stream_reads_as_up(self):
        connection_state.configure(_Redis())
        bot = uuid4()

        await connection_state.record_up(bot)
        found = await connection_state.read(bot)

        assert found is not None
        assert found.state == "up"
        assert found.reason is None

    async def test_a_refused_stream_carries_what_to_do_about_it(self):
        """The reason is rendered in the product, so it names the credential to
        add rather than quoting whatever the vendor's client said."""
        connection_state.configure(_Redis())
        bot = uuid4()

        await connection_state.record_down(bot, "Add the xapp- token in the bot's settings.")
        found = await connection_state.read(bot)

        assert found is not None
        assert found.state == "down"
        assert found.reason == "Add the xapp- token in the bot's settings."

    async def test_the_latest_word_wins(self):
        """A stream that failed and then opened is up, not both."""
        connection_state.configure(_Redis())
        bot = uuid4()

        await connection_state.record_down(bot, "nope")
        await connection_state.record_up(bot)

        found = await connection_state.read(bot)
        assert found is not None and found.state == "up"


class TestWhenNothingIsKnown:
    async def test_no_redis_reads_as_unknown_rather_than_broken(self):
        """A deployment with no Redis configured must not grow a red badge on
        every bot it has - that is the same defect, reported backwards."""
        connection_state.configure(None)

        assert await connection_state.read(uuid4()) is None

    async def test_a_bot_nobody_recorded_reads_as_unknown(self):
        connection_state.configure(_Redis())

        assert await connection_state.read(uuid4()) is None

    async def test_writing_without_redis_is_a_no_op_rather_than_a_failure(self):
        """A supervisor must not fail to open a stream because it could not
        describe itself."""
        connection_state.configure(None)

        await connection_state.record_up(uuid4())
        await connection_state.record_down(uuid4(), "nope")
        await connection_state.forget(uuid4())

    async def test_a_redis_that_raises_costs_the_badge_and_nothing_else(self):
        failing = _Redis()
        failing.get = AsyncMock(side_effect=RuntimeError("redis is down"))  # type: ignore[method-assign]
        failing.set = AsyncMock(side_effect=RuntimeError("redis is down"))  # type: ignore[method-assign]
        connection_state.configure(failing)

        await connection_state.record_up(uuid4())
        assert await connection_state.read(uuid4()) is None

    @pytest.mark.parametrize("stored", ["not json", "{}", '{"state": "sideways"}', "[]"])
    async def test_an_entry_it_cannot_read_is_unknown(self, stored: str):
        """Anything but the two states it wrote itself, including a shape from a
        version of this module that no longer exists."""
        redis = _Redis()
        bot = uuid4()
        redis.store[f"channel:conn:{bot}"] = stored
        connection_state.configure(redis)

        assert await connection_state.read(bot) is None


class TestForgetting:
    async def test_a_stopped_bot_stops_reporting(self):
        """A paused or deleted bot has no connection by design, and the listing
        already says `Paused`. Leaving a `down` beside it reports a decision as a
        fault."""
        connection_state.configure(_Redis())
        bot = uuid4()
        await connection_state.record_down(bot, "nope")

        await connection_state.forget(bot)

        assert await connection_state.read(bot) is None

    async def test_the_entry_expires_rather_than_outliving_its_process(self):
        """A killed worker's last word must not still be on screen an hour
        later: a bot whose supervisor is gone is unknown, not down."""
        recorded: dict[str, int | None] = {}

        class _Recording(_Redis):
            async def set(self, key: str, value: str, ttl: int | None = None) -> None:
                recorded["ttl"] = ttl
                await super().set(key, value, ttl)

        connection_state.configure(_Recording())
        await connection_state.record_up(uuid4())

        assert recorded["ttl"] == connection_state.TTL_SECONDS


class TestTheStoredShape:
    async def test_it_is_json_with_both_fields(self):
        """Read by `read` alone, but a shape somebody will look at in redis-cli
        when a badge says something they did not expect."""
        redis = _Redis()
        connection_state.configure(redis)
        bot = uuid4()

        await connection_state.record_down(bot, "Add the xapp- token.")

        assert json.loads(redis.store[f"channel:conn:{bot}"]) == {
            "state": "down",
            "reason": "Add the xapp- token.",
        }
