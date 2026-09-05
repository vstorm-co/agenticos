"""What the channel router keeps per chat, and for how long.

Two maps in the router used to grow for the life of the process. The per-chat
lock was keyed on the thread, which on Slack is a fresh key for every top-level
message, and nothing ever removed an entry - one `asyncio.Lock` retained per
message a busy workspace ever sent. The rate-limit bucket kept one entry per chat
account for ever, and counted in this process alone, so four API workers let
through four times the allowance a bot's policy named.

So the assertions here are about size and about where the count lives: N
messages leave no lock behind, two messages in one chat still take turns, and
the allowance is consumed from the Redis every worker shares.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.services import rate_limit
from app.services.channels import router as router_module
from app.services.channels.base import IncomingMessage, thread_key
from app.services.channels.router import ChannelMessageRouter, _ChatLocks

pytestmark = pytest.mark.anyio


def _message(**overrides: Any) -> IncomingMessage:
    defaults: dict[str, Any] = {
        "platform": "slack",
        "bot_id": "bot-1",
        "platform_user_id": "U1",
        "platform_chat_id": "C1",
        "chat_type": "channel",
        "text": "hello",
        "message_id": "1723300000.000100",
    }
    defaults.update(overrides)
    return IncomingMessage(**defaults)


def _top_level_slack_message(n: int) -> IncomingMessage:
    """What the Slack adapter hands the router for the n-th message in a channel:
    a thread of its own, keyed on the message's own `ts`."""
    ts = f"1723300000.{n:06d}"
    return _message(platform_chat_id=thread_key("C1", thread_id="", message_id=ts), message_id=ts)


@pytest.fixture
def locks(monkeypatch: pytest.MonkeyPatch) -> _ChatLocks:
    """A lock map of this test's own, so a count means what it says."""
    fresh = _ChatLocks()
    monkeypatch.setattr(router_module, "_chat_locks", fresh)
    monkeypatch.setattr(router_module, "claim_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(router_module, "release_delivery", AsyncMock())
    return fresh


class TestTheLockAChatIsProcessedUnder:
    async def test_the_chat_lock_map_does_not_grow_per_message(self, locks: _ChatLocks):
        router = ChannelMessageRouter()
        with patch.object(ChannelMessageRouter, "_route_inner", new=AsyncMock()):
            for n in range(50):
                await router.route(_top_level_slack_message(n), MagicMock())

        assert len(locks) == 0

    async def test_two_messages_in_one_chat_take_turns_and_leave_nothing_behind(
        self, locks: _ChatLocks
    ):
        """The lock still serialises a chat - that is what it is for - and a
        waiter keeps the entry alive exactly until it has had its turn."""
        router = ChannelMessageRouter()
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        order: list[str] = []

        async def slow_turn(incoming: IncomingMessage, db: Any) -> None:
            order.append(f"start {incoming.message_id}")
            if incoming.message_id == "one":
                first_started.set()
                await release_first.wait()
            order.append(f"end {incoming.message_id}")

        with patch.object(
            ChannelMessageRouter, "_route_inner", new=AsyncMock(side_effect=slow_turn)
        ):
            first = asyncio.create_task(router.route(_message(message_id="one"), MagicMock()))
            await first_started.wait()
            second = asyncio.create_task(router.route(_message(message_id="two"), MagicMock()))
            await asyncio.sleep(0)

            assert len(locks) == 1, "one chat in flight, one entry - however many wait on it"
            assert order == ["start one"]

            release_first.set()
            await asyncio.gather(first, second)

        assert order == ["start one", "end one", "start two", "end two"]
        assert len(locks) == 0

    async def test_messages_in_different_chats_do_not_wait_on_each_other(self, locks: _ChatLocks):
        router = ChannelMessageRouter()
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        seen: list[str] = []

        async def turn(incoming: IncomingMessage, db: Any) -> None:
            seen.append(incoming.platform_chat_id)
            if incoming.platform_chat_id == "C1":
                first_started.set()
                await release_first.wait()

        with patch.object(ChannelMessageRouter, "_route_inner", new=AsyncMock(side_effect=turn)):
            blocked = asyncio.create_task(
                router.route(_message(platform_chat_id="C1"), MagicMock())
            )
            await first_started.wait()
            await router.route(_message(platform_chat_id="C2"), MagicMock())

            assert seen == ["C1", "C2"]
            assert len(locks) == 1

            release_first.set()
            await blocked

        assert len(locks) == 0

    async def test_a_turn_that_raises_still_drops_its_lock(self, locks: _ChatLocks):
        router = ChannelMessageRouter()
        with (
            patch.object(
                ChannelMessageRouter, "_route_inner", new=AsyncMock(side_effect=RuntimeError("no"))
            ),
            pytest.raises(RuntimeError),
        ):
            await router.route(_message(), MagicMock())

        assert len(locks) == 0


@pytest.fixture
def _unmetered():
    rate_limit.configure(None)
    yield
    rate_limit.configure(None)


def _counting(counts: list[int]) -> MagicMock:
    client = MagicMock()
    client.count_in_window = AsyncMock(side_effect=counts)
    return client


def _bot(policy: dict[str, Any] | None = None) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), access_policy=policy or {})


@pytest.mark.usefixtures("_unmetered")
class TestTheAllowanceAChatAccountGets:
    async def test_the_allowance_is_counted_in_the_shared_redis(self):
        """Not in this process: four workers counting separately let through four
        times the number the policy names, and read as though they did not."""
        redis = _counting([1])
        rate_limit.configure(redis)
        bot = _bot()

        await ChannelMessageRouter()._check_rate_limit(bot, "identity-1")

        key = redis.count_in_window.await_args.args[0]
        assert key == f"ratelimit:channel:bot:{bot.id}:identity:identity-1"
        assert redis.count_in_window.await_args.kwargs["ttl"] == 60

    async def test_the_message_past_the_allowance_is_refused(self):
        rate_limit.configure(_counting([10, 11]))
        bot = _bot()
        router = ChannelMessageRouter()

        await router._check_rate_limit(bot, "identity-1")
        with pytest.raises(BadRequestError) as refused:
            await router._check_rate_limit(bot, "identity-1")

        assert "slow down" in refused.value.message

    async def test_the_bots_policy_sets_the_allowance(self):
        rate_limit.configure(_counting([3]))

        with pytest.raises(BadRequestError):
            await ChannelMessageRouter()._check_rate_limit(_bot({"rate_limit_rpm": 2}), "id")

    async def test_a_policy_stored_as_json_is_read_the_same_way(self):
        rate_limit.configure(_counting([3]))

        with pytest.raises(BadRequestError):
            await ChannelMessageRouter()._check_rate_limit(_bot('{"rate_limit_rpm": 2}'), "id")

    async def test_a_deployment_with_no_limiter_answers_rather_than_refusing(self, caplog):
        """The same fail-open the limiter applies everywhere: a cache that is
        down is logged, a message that is dropped is silence in front of a user."""
        await ChannelMessageRouter()._check_rate_limit(_bot(), "identity-1")

        assert "Rate limiting not configured" in caplog.text
