"""The membership check behind the participant model (#641).

`messages.channel_identity_id` says who spoke; these tests pin that nothing
here treats it as who may read. Every claim is confirmed against the platform,
every way the platform cannot answer refuses, and the cache never widens an
answer - it only remembers one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.repositories.conversation import ParticipationClaim
from app.services.channels import membership
from app.services.channels.base import ChannelDirectoryUnsupported

pytestmark = pytest.mark.anyio


class FakeRedis:
    """The two calls membership makes, over a dict."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        self.store[key] = value
        if ttl is not None:
            self.ttls[key] = ttl
        return True


class BrokenRedis:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis is down")

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        raise ConnectionError("redis is down")


@pytest.fixture(autouse=True)
def unconfigured():
    """Every test starts and ends with no Redis handed over."""
    membership.configure(None)
    yield
    membership.configure(None)


def _bot(platform: str = "mattermost"):
    bot = MagicMock()
    bot.id = uuid4()
    bot.platform = platform
    bot.api_base_url = "https://mm.example.com"
    return bot


def _adapter(answer: bool | BaseException) -> MagicMock:
    adapter = MagicMock()
    if isinstance(answer, BaseException):
        adapter.is_channel_member = AsyncMock(side_effect=answer)
    else:
        adapter.is_channel_member = AsyncMock(return_value=answer)
    return adapter


class TestIsStillMember:
    async def test_the_platforms_yes_is_a_yes_and_is_cached(self):
        redis = FakeRedis()
        membership.configure(redis)
        bot = _bot()
        adapter = _adapter(True)

        with (
            patch("app.services.channels.membership.get_adapter", return_value=adapter),
            patch("app.services.channels.membership.unseal_bot_token", return_value="token"),
        ):
            assert await membership.is_still_member(bot, "town-square", "acc-1") is True

        adapter.is_channel_member.assert_awaited_once_with(
            "token", "town-square", "acc-1", api_base_url="https://mm.example.com"
        )
        key = membership._key(bot.id, "town-square", "acc-1")
        assert redis.store[key] == "1"
        assert redis.ttls[key] == membership.MEMBERSHIP_TTL_SECONDS

    async def test_the_platforms_no_is_a_no_and_is_cached(self):
        redis = FakeRedis()
        membership.configure(redis)
        bot = _bot()

        with (
            patch("app.services.channels.membership.get_adapter", return_value=_adapter(False)),
            patch("app.services.channels.membership.unseal_bot_token", return_value="token"),
        ):
            assert await membership.is_still_member(bot, "town-square", "acc-1") is False

        assert redis.store[membership._key(bot.id, "town-square", "acc-1")] == "0"

    async def test_a_cached_answer_never_reaches_the_platform(self):
        redis = FakeRedis()
        membership.configure(redis)
        bot = _bot()
        redis.store[membership._key(bot.id, "town-square", "acc-1")] = "1"
        redis.store[membership._key(bot.id, "town-square", "acc-2")] = "0"

        with patch("app.services.channels.membership.get_adapter") as get_adapter:
            assert await membership.is_still_member(bot, "town-square", "acc-1") is True
            assert await membership.is_still_member(bot, "town-square", "acc-2") is False

        get_adapter.assert_not_called()

    async def test_a_platform_that_cannot_answer_refuses(self):
        """`ChannelDirectoryUnsupported` is the safe default the issue names:
        a claim nobody can check is a claim, not access."""
        bot = _bot("telegram")
        unsupported = _adapter(ChannelDirectoryUnsupported("telegram will not tell a bot"))

        with (
            patch("app.services.channels.membership.get_adapter", return_value=unsupported),
            patch("app.services.channels.membership.unseal_bot_token", return_value="token"),
        ):
            assert await membership.is_still_member(bot, "-100123", "42") is False

    async def test_a_failing_platform_call_refuses_rather_than_admits(self):
        bot = _bot()

        with (
            patch(
                "app.services.channels.membership.get_adapter",
                return_value=_adapter(ConnectionError("timeout")),
            ),
            patch("app.services.channels.membership.unseal_bot_token", return_value="token"),
        ):
            assert await membership.is_still_member(bot, "town-square", "acc-1") is False

    async def test_an_unregistered_adapter_refuses(self):
        """A platform with no adapter in this process cannot vouch for anybody."""
        bot = _bot("nothing-registered")

        assert await membership.is_still_member(bot, "town-square", "acc-1") is False

    async def test_a_refusal_is_cached_so_a_dead_platform_is_not_hammered(self):
        redis = FakeRedis()
        membership.configure(redis)
        bot = _bot()
        adapter = _adapter(ConnectionError("timeout"))

        with (
            patch("app.services.channels.membership.get_adapter", return_value=adapter),
            patch("app.services.channels.membership.unseal_bot_token", return_value="token"),
        ):
            await membership.is_still_member(bot, "town-square", "acc-1")
            await membership.is_still_member(bot, "town-square", "acc-1")

        adapter.is_channel_member.assert_awaited_once()

    async def test_no_redis_means_slower_never_wider(self):
        """Unconfigured, every check goes to the platform - and the answer is
        still the platform's."""
        bot = _bot()
        adapter = _adapter(True)

        with (
            patch("app.services.channels.membership.get_adapter", return_value=adapter),
            patch("app.services.channels.membership.unseal_bot_token", return_value="token"),
        ):
            assert await membership.is_still_member(bot, "town-square", "acc-1") is True
            assert await membership.is_still_member(bot, "town-square", "acc-1") is True

        assert adapter.is_channel_member.await_count == 2

    async def test_a_broken_cache_reads_as_a_miss_and_the_write_is_best_effort(self):
        membership.configure(BrokenRedis())
        bot = _bot()
        adapter = _adapter(True)

        with (
            patch("app.services.channels.membership.get_adapter", return_value=adapter),
            patch("app.services.channels.membership.unseal_bot_token", return_value="token"),
        ):
            assert await membership.is_still_member(bot, "town-square", "acc-1") is True

        adapter.is_channel_member.assert_awaited_once()


def _claim(conversation_id, bot_id, chat: str = "town-square", account: str = "acc-1"):
    return ParticipationClaim(
        conversation_id=conversation_id,
        platform_user_id=account,
        bot_id=bot_id,
        platform_chat_id=chat,
    )


class TestConfirmedParticipantThreads:
    async def test_only_threads_the_platform_confirms_survive(self):
        reader, organization = uuid4(), uuid4()
        kept_thread, lost_thread = uuid4(), uuid4()
        bot = _bot()
        claims = [
            _claim(kept_thread, bot.id, chat="kept"),
            _claim(lost_thread, bot.id, chat="lost"),
        ]

        async def answer(found_bot, chat, account):
            return chat == "kept"

        with (
            patch(
                "app.services.channels.membership.conversation_repo.participation_claims",
                AsyncMock(return_value=claims),
            ) as participation_claims,
            patch(
                "app.services.channels.membership.channel_bot_repo.get_by_ids",
                AsyncMock(return_value={bot.id: bot}),
            ),
            patch(
                "app.services.channels.membership.is_still_member", AsyncMock(side_effect=answer)
            ),
        ):
            confirmed = await membership.confirmed_participant_threads(
                AsyncMock(), user_id=reader, organization_id=organization
            )

        assert confirmed == {kept_thread}
        assert participation_claims.await_args.kwargs == {
            "user_id": reader,
            "organization_id": organization,
        }

    async def test_no_claims_asks_nothing(self):
        """The common case - a dashboard-only user - costs no bot load and no
        platform call."""
        with (
            patch(
                "app.services.channels.membership.conversation_repo.participation_claims",
                AsyncMock(return_value=[]),
            ),
            patch("app.services.channels.membership.channel_bot_repo.get_by_ids") as get_by_ids,
        ):
            confirmed = await membership.confirmed_participant_threads(
                AsyncMock(), user_id=uuid4(), organization_id=uuid4()
            )

        assert confirmed == set()
        get_by_ids.assert_not_called()

    async def test_a_deleted_bot_takes_its_claims_with_it(self):
        """A claim whose bot row is gone cannot be checked, so it is refused."""
        thread = uuid4()

        with (
            patch(
                "app.services.channels.membership.conversation_repo.participation_claims",
                AsyncMock(return_value=[_claim(thread, uuid4())]),
            ),
            patch(
                "app.services.channels.membership.channel_bot_repo.get_by_ids",
                AsyncMock(return_value={}),
            ),
            patch("app.services.channels.membership.is_still_member") as is_still_member,
        ):
            confirmed = await membership.confirmed_participant_threads(
                AsyncMock(), user_id=uuid4(), organization_id=uuid4()
            )

        assert confirmed == set()
        is_still_member.assert_not_called()

    async def test_one_room_is_one_question_however_many_threads_and_speakers(self):
        """Slack folds a thread into `platform_chat_id`, so several conversations
        can share one (bot, chat, account) - the platform is asked once."""
        bot = _bot()
        first, second = uuid4(), uuid4()
        claims = [_claim(first, bot.id), _claim(second, bot.id)]

        with (
            patch(
                "app.services.channels.membership.conversation_repo.participation_claims",
                AsyncMock(return_value=claims),
            ),
            patch(
                "app.services.channels.membership.channel_bot_repo.get_by_ids",
                AsyncMock(return_value={bot.id: bot}),
            ),
            patch(
                "app.services.channels.membership.is_still_member", AsyncMock(return_value=True)
            ) as is_still_member,
        ):
            confirmed = await membership.confirmed_participant_threads(
                AsyncMock(), user_id=uuid4(), organization_id=uuid4()
            )

        assert confirmed == {first, second}
        is_still_member.assert_awaited_once()


class TestConfirmsParticipation:
    async def test_a_confirmed_claim_opens_the_thread(self):
        thread, reader = uuid4(), uuid4()
        bot = _bot()

        with (
            patch(
                "app.services.channels.membership.conversation_repo.participation_claims",
                AsyncMock(return_value=[_claim(thread, bot.id)]),
            ) as participation_claims,
            patch(
                "app.services.channels.membership.channel_bot_repo.get_by_ids",
                AsyncMock(return_value={bot.id: bot}),
            ),
            patch("app.services.channels.membership.is_still_member", AsyncMock(return_value=True)),
        ):
            assert (
                await membership.confirms_participation(
                    AsyncMock(), conversation_id=thread, user_id=reader
                )
                is True
            )

        assert participation_claims.await_args.kwargs == {
            "user_id": reader,
            "conversation_id": thread,
        }

    async def test_a_removed_member_is_refused_the_thread(self):
        """The defect itself: they spoke, the platform since removed them, the
        thread does not open."""
        thread = uuid4()
        bot = _bot()

        with (
            patch(
                "app.services.channels.membership.conversation_repo.participation_claims",
                AsyncMock(return_value=[_claim(thread, bot.id)]),
            ),
            patch(
                "app.services.channels.membership.channel_bot_repo.get_by_ids",
                AsyncMock(return_value={bot.id: bot}),
            ),
            patch(
                "app.services.channels.membership.is_still_member", AsyncMock(return_value=False)
            ),
        ):
            assert (
                await membership.confirms_participation(
                    AsyncMock(), conversation_id=thread, user_id=uuid4()
                )
                is False
            )

    async def test_a_thread_with_no_claims_does_not_open(self):
        """Never spoke there - or the session moved on and nothing names the
        channel any more. Both refuse; owner and share are other doors."""
        with patch(
            "app.services.channels.membership.conversation_repo.participation_claims",
            AsyncMock(return_value=[]),
        ):
            assert (
                await membership.confirms_participation(
                    AsyncMock(), conversation_id=uuid4(), user_id=uuid4()
                )
                is False
            )
