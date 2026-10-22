"""Startup opens a stream per polling bot, and one bot it cannot unseal does not
stop the API from starting.

Found on a machine where the quickstart had attached to a development stack's
database: a Slack bot sealed under the developer's `VAULT_MASTER_KEY` raised out
of `_start_channel_polling`, the lifespan failed, and the container crash-looped.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app import main
from app.core.exceptions import AppException, BadRequestError, ConfigurationError
from app.services.channels import stream_lease
from app.services.channels.stream_lease import StreamLeases

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def leases(monkeypatch: pytest.MonkeyPatch) -> StreamLeases:
    """A process with no Redis and nothing held, so no test inherits another's bots."""
    fresh = StreamLeases(None)
    monkeypatch.setattr(stream_lease, "_leases", fresh)
    return fresh


class _Session:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *_exc: Any) -> None:
        return None


def _bot(platform: str = "telegram") -> MagicMock:
    return MagicMock(id=uuid4(), api_base_url=None, platform=platform)


def _rows(
    monkeypatch: pytest.MonkeyPatch, bots: list[MagicMock], *, now: list[Any] | None = None
) -> AsyncMock:
    """The ids the pass claims from, and the rows it reads for the bots it claimed."""
    monkeypatch.setattr(main, "get_db_context", _Session)
    monkeypatch.setattr(
        main, "get_active_polling_bot_ids", AsyncMock(return_value=[bot.id for bot in bots])
    )
    read = AsyncMock(return_value=bots if now is None else now)
    monkeypatch.setattr(main, "get_active_polling_bots", read)
    return read


@pytest.mark.parametrize(
    "refusal",
    [
        BadRequestError(message="Failed to decrypt secret - wrong master key or owner"),
        ConfigurationError(message="No vault key configured for version 3"),
    ],
    ids=["wrong-key", "missing-key-version"],
)
async def test_a_bot_whose_token_cannot_be_unsealed_is_skipped_and_the_rest_start(
    monkeypatch: pytest.MonkeyPatch, refusal: AppException
) -> None:
    """Both refusals the vault raises: a ciphertext the configured key cannot
    open, and a key version `VAULT_MASTER_KEYS` does not hold at all. The bot is
    recorded `down` with a reason an operator can act on, so the console does
    not go on showing a heartbeat from the run before the restart."""
    sealed_elsewhere, readable = _bot("slack"), _bot("slack")
    _rows(monkeypatch, [sealed_elsewhere, readable])

    def unseal(bot: MagicMock) -> str:
        if bot is sealed_elsewhere:
            raise refusal
        return "xoxb-readable"

    monkeypatch.setattr(main, "unseal_bot_token", unseal)
    monkeypatch.setattr(main, "unseal_slack_app_token", MagicMock(return_value="xapp-readable"))
    opened = AsyncMock()
    monkeypatch.setattr(main, "open_inbound_stream", opened)
    down = AsyncMock()
    monkeypatch.setattr(main.channel_connection_state, "record_down", down)

    await main._start_channel_polling("slack")

    opened.assert_awaited_once()
    assert opened.await_args.kwargs["bot_id"] == str(readable.id)
    assert opened.await_args.kwargs["token"] == "xoxb-readable"
    down.assert_awaited_once()
    assert down.await_args.args[0] == sealed_elsewhere.id
    assert refusal.message in down.await_args.args[1]


async def test_a_bot_with_a_readable_token_still_raises_when_its_stream_cannot_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the vault refusal is absorbed. A stream that fails to open is the
    adapter's failure, and the lifespan's own handler around this call decides
    what to do with it - as before."""
    _rows(monkeypatch, [_bot("slack")])
    monkeypatch.setattr(main, "unseal_bot_token", MagicMock(return_value="xoxb"))
    monkeypatch.setattr(main, "unseal_slack_app_token", MagicMock(return_value=None))
    monkeypatch.setattr(main, "open_inbound_stream", AsyncMock(side_effect=OSError("refused")))

    with pytest.raises(OSError):
        await main._start_channel_polling("slack")


class _SharedRedis:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.keys:
            return False
        self.keys[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.keys.get(key)

    async def delete_if_equal(self, key: str, value: str) -> bool:
        if self.keys.get(key) != value:
            return False
        del self.keys[key]
        return True


async def test_two_workers_open_one_stream_per_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both workers run the startup pass against one Redis; the bot gets one
    stream, and the second worker's later passes leave it alone (#2168)."""
    bot = _bot()
    _rows(monkeypatch, [bot])
    monkeypatch.setattr(main, "unseal_bot_token", MagicMock(return_value="123:abc"))
    monkeypatch.setattr(main, "unseal_slack_app_token", MagicMock(return_value=None))
    opened = AsyncMock()
    monkeypatch.setattr(main, "open_inbound_stream", opened)
    redis = _SharedRedis()

    for holder in ("first", "second", "second"):
        monkeypatch.setattr(stream_lease, "_leases", StreamLeases(redis, holder=holder))  # ty: ignore[invalid-argument-type]
        await main._start_channel_polling("telegram")

    opened.assert_awaited_once()
    assert redis.keys == {f"channel:stream:{bot.id}": "first"}


async def test_a_bot_that_cannot_be_unsealed_is_refused_once_not_every_pass(
    monkeypatch: pytest.MonkeyPatch, leases: StreamLeases
) -> None:
    """Held with no stream, so the pass every few seconds does not log the same
    refusal again; entering the token again takes the lease and opens it."""
    bot = _bot()
    _rows(monkeypatch, [bot])
    unseal = MagicMock(side_effect=BadRequestError(message="wrong master key"))
    monkeypatch.setattr(main, "unseal_bot_token", unseal)
    monkeypatch.setattr(main.channel_connection_state, "record_down", AsyncMock())

    await main._start_channel_polling("telegram")
    await main._start_channel_polling("telegram")

    unseal.assert_called_once()
    assert leases.held == {str(bot.id): "telegram"}


async def test_a_bot_paused_after_the_first_read_is_given_back_not_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pass reads the rows, then claims: a pause committed in between left
    the lease free to claim, and the row read before it would reopen the bot."""
    bot = _bot()
    _rows(monkeypatch, [bot], now=[])
    opened = AsyncMock()
    monkeypatch.setattr(main, "open_inbound_stream", opened)
    redis = _SharedRedis()
    leases = StreamLeases(redis, holder="pass")  # ty: ignore[invalid-argument-type]
    monkeypatch.setattr(stream_lease, "_leases", leases)

    await main._start_channel_polling("telegram")

    opened.assert_not_awaited()
    assert redis.keys == {}
    assert leases.held == {}


async def test_a_claimed_bot_opens_with_the_row_as_it_is_now_and_only_if_still_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, now = _bot("mattermost"), _bot("mattermost")
    now.id = before.id
    now.api_base_url = "https://chat.example.com"
    _rows(monkeypatch, [before], now=[now])
    monkeypatch.setattr(main, "unseal_bot_token", MagicMock(return_value="tok"))
    monkeypatch.setattr(main, "unseal_slack_app_token", MagicMock(return_value=None))
    opened = AsyncMock()
    monkeypatch.setattr(main, "open_inbound_stream", opened)

    await main._start_channel_polling("mattermost")

    assert opened.await_args.kwargs["api_base_url"] == "https://chat.example.com"
    assert opened.await_args.kwargs["take_over"] is False


async def test_the_keeper_asks_about_every_platform_in_one_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One query finds the bots of all three platforms (#2227), and only the bots a
    pass claimed are read in full - their sealed tokens with them."""
    telegram, slack = _bot("telegram"), _bot("slack")
    read = _rows(monkeypatch, [telegram, slack])
    monkeypatch.setattr(main, "unseal_bot_token", MagicMock(return_value="tok"))
    monkeypatch.setattr(main, "unseal_slack_app_token", MagicMock(return_value=None))
    opened = AsyncMock()
    monkeypatch.setattr(main, "open_inbound_stream", opened)

    await main._start_channel_polling(*main._POLLING_PLATFORMS)
    # Everything is held now: the next pass reads ids and no rows at all.
    await main._start_channel_polling(*main._POLLING_PLATFORMS)

    assert main.get_active_polling_bot_ids.await_count == 2  # ty: ignore[unresolved-attribute]
    read.assert_awaited_once()
    assert read.await_args.args[1:] == main._POLLING_PLATFORMS
    assert set(read.await_args.kwargs["ids"]) == {telegram.id, slack.id}
    assert {
        (call.kwargs["bot_id"], call.kwargs["platform"]) for call in opened.await_args_list
    } == {(str(telegram.id), "telegram"), (str(slack.id), "slack")}


async def _passes(monkeypatch: pytest.MonkeyPatch, count: int) -> AsyncMock:
    """Run the keeper for `count` passes, its sleep and its renewal stubbed out."""
    slept = 0

    async def sleep(_seconds: float) -> None:
        nonlocal slept
        slept += 1
        if slept > count:
            raise asyncio.CancelledError

    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    monkeypatch.setattr(stream_lease.leases(), "renew", AsyncMock(return_value=[]))
    passes = AsyncMock()
    monkeypatch.setattr(main, "_start_channel_polling", passes)
    with pytest.raises(asyncio.CancelledError):
        await main._keep_channel_streams()
    return passes


async def test_the_keeper_reads_which_bots_should_stream_once_a_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It was every ten seconds in every worker: most of prod's statements. The
    leases are still checked on each pass, so a dead holder is replaced as fast."""
    bot = _bot()
    _rows(monkeypatch, [bot])

    passes = await _passes(monkeypatch, 3)

    assert main.get_active_polling_bot_ids.await_count == 1  # ty: ignore[unresolved-attribute]
    assert passes.await_count == 3
    assert all(call.kwargs["bot_ids"] == [str(bot.id)] for call in passes.await_args_list)


async def test_the_keeper_reads_them_again_once_the_minute_is_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rows(monkeypatch, [_bot()])
    monkeypatch.setattr(main, "_DISCOVER_BOTS_EVERY_SECONDS", 0.0)

    await _passes(monkeypatch, 3)

    assert main.get_active_polling_bot_ids.await_count == 3  # ty: ignore[unresolved-attribute]
