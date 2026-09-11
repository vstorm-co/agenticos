"""Startup opens a stream per polling bot, and one bot it cannot unseal does not
stop the API from starting.

Found on a machine where the quickstart had attached to a development stack's
database: a Slack bot sealed under the developer's `VAULT_MASTER_KEY` raised out
of `_start_channel_polling`, the lifespan failed, and the container crash-looped.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app import main
from app.core.exceptions import BadRequestError

pytestmark = pytest.mark.anyio


class _Session:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *_exc: Any) -> None:
        return None


def _bot() -> MagicMock:
    return MagicMock(id=uuid4(), api_base_url=None)


async def test_a_bot_whose_token_cannot_be_unsealed_is_skipped_and_the_rest_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sealed_elsewhere, readable = _bot(), _bot()
    monkeypatch.setattr(main, "get_db_context", lambda: _Session())
    monkeypatch.setattr(
        main, "get_active_polling_bots", AsyncMock(return_value=[sealed_elsewhere, readable])
    )

    def unseal(bot: MagicMock) -> str:
        if bot is sealed_elsewhere:
            raise BadRequestError(message="Failed to decrypt secret - wrong master key or owner")
        return "xoxb-readable"

    monkeypatch.setattr(main, "unseal_bot_token", unseal)
    monkeypatch.setattr(main, "unseal_slack_app_token", lambda _bot: "xapp-readable")
    opened = AsyncMock()
    monkeypatch.setattr(main, "open_inbound_stream", opened)

    await main._start_channel_polling("slack")

    opened.assert_awaited_once()
    assert opened.await_args.kwargs["bot_id"] == str(readable.id)
    assert opened.await_args.kwargs["token"] == "xoxb-readable"


async def test_a_bot_with_a_readable_token_still_raises_when_its_stream_cannot_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the vault refusal is absorbed. A stream that fails to open is the
    adapter's failure, and the lifespan's own handler around this call decides
    what to do with it - as before."""
    monkeypatch.setattr(main, "get_db_context", lambda: _Session())
    monkeypatch.setattr(main, "get_active_polling_bots", AsyncMock(return_value=[_bot()]))
    monkeypatch.setattr(main, "unseal_bot_token", lambda _bot: "xoxb")
    monkeypatch.setattr(main, "unseal_slack_app_token", lambda _bot: None)
    monkeypatch.setattr(main, "open_inbound_stream", AsyncMock(side_effect=OSError("refused")))

    with pytest.raises(OSError):
        await main._start_channel_polling("slack")
