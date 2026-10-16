"""Ending a call on the provider's side (#54, Q3). 404 means it is already gone."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest
from pydantic import SecretStr

from app.core.secret_kinds import ApiKeySecret
from app.services.voice.hangup import HangUpTarget, hang_up

pytestmark = pytest.mark.anyio
_KEY = ApiKeySecret(api_key=SecretStr("sk-test-key"))


def _client(hangup: AsyncMock) -> MagicMock:
    client = MagicMock()
    client.realtime.calls.hangup = hangup
    client.close = AsyncMock()
    return client


async def test_a_webrtc_call_is_hung_up_with_its_own_key():
    hangup = AsyncMock()
    with patch("app.services.voice.hangup.AsyncOpenAI", return_value=_client(hangup)) as made:
        assert await hang_up(
            HangUpTarget(
                transport="webrtc", provider="openai", provider_call_id="rtc_1", secret=_KEY
            )
        )
    hangup.assert_awaited_once_with("rtc_1")
    assert made.call_args.kwargs["api_key"] == "sk-test-key"


async def test_a_call_the_provider_no_longer_knows_counts_as_ended():
    response = httpx.Response(
        404, request=httpx.Request("POST", "https://api.openai.com/v1/realtime/calls/x/hangup")
    )
    hangup = AsyncMock(side_effect=openai.NotFoundError("gone", response=response, body=None))
    with patch("app.services.voice.hangup.AsyncOpenAI", return_value=_client(hangup)):
        assert await hang_up(
            HangUpTarget(transport="webrtc", provider="openai", provider_call_id="x", secret=_KEY)
        )


async def test_a_failed_hang_up_reports_false_for_the_reaper_to_retry():
    hangup = AsyncMock(
        side_effect=openai.APIConnectionError(request=httpx.Request("POST", "https://x"))
    )
    with patch("app.services.voice.hangup.AsyncOpenAI", return_value=_client(hangup)):
        assert not await hang_up(
            HangUpTarget(transport="webrtc", provider="openai", provider_call_id="x", secret=_KEY)
        )


async def test_a_relay_call_ends_when_its_socket_closes():
    assert await hang_up(
        HangUpTarget(transport="relay", provider="google", provider_call_id=None, secret=None)
    )


async def test_a_webrtc_call_that_was_never_answered_has_nothing_to_hang_up():
    assert await hang_up(
        HangUpTarget(transport="webrtc", provider="openai", provider_call_id=None, secret=None)
    )


async def test_a_webrtc_call_whose_key_is_gone_cannot_be_hung_up():
    assert not await hang_up(
        HangUpTarget(transport="webrtc", provider="openai", provider_call_id="x", secret=None)
    )


async def test_a_call_is_hung_up_from_its_row_with_its_own_organizations_key():
    from types import SimpleNamespace
    from uuid import uuid4

    from app.services.voice.hangup import hang_up_row

    row = SimpleNamespace(
        organization_id=uuid4(),
        secret_id=uuid4(),
        transport="webrtc",
        provider="openai",
        provider_call_id="rtc_9",
    )
    with (
        patch(
            "app.services.voice.hangup.OrganizationSecretService.voice_call_key",
            AsyncMock(return_value=_KEY),
        ) as key,
        patch("app.services.voice.hangup.hang_up", AsyncMock(return_value=True)) as hung,
    ):
        assert await hang_up_row(MagicMock(), row)
    key.assert_awaited_once_with(row.organization_id, row.secret_id)
    assert hung.await_args.args[0].provider_call_id == "rtc_9"


async def test_a_key_that_cannot_be_unsealed_reads_as_not_hung_up_rather_than_raising(caplog):
    """After a master-key rotation one row's envelope will not open. A raise here
    aborted the whole sweep and, at the head of its oldest-first queue, every
    sweep after it; `False` lets the reaper's one-hour rule retire the row (RR-c01)."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.core.exceptions import BadRequestError
    from app.services.voice.hangup import hang_up_row

    row = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        secret_id=uuid4(),
        transport="webrtc",
        provider="openai",
        provider_call_id="rtc_9",
    )
    unreadable = BadRequestError(message="Failed to decrypt secret - wrong master key or owner")
    with (
        patch(
            "app.services.voice.hangup.OrganizationSecretService.voice_call_key",
            AsyncMock(side_effect=unreadable),
        ),
        patch("app.services.voice.hangup.hang_up", AsyncMock(return_value=True)) as hung,
    ):
        assert not await hang_up_row(MagicMock(), row)
    hung.assert_not_awaited()
    assert "voice_hangup_key_unreadable" in caplog.text
    (record,) = [r for r in caplog.records if r.getMessage() == "voice_hangup_key_unreadable"]
    assert record.call_id == str(row.id)
    assert not hasattr(record, "secret_id")
