"""Tests for the Slack events webhook - verification with the bot's own secret.

The deployment-wide signing secret is gone; each bot verifies inbound events
with the secret sealed on its row. What has to hold: an unverifiable request
never reaches processing, and a bot without a secret refuses with the sentence
that says where to add one.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routes.v1.slack_webhook import slack_events

pytestmark = pytest.mark.anyio

_MODULE = "app.api.routes.v1.slack_webhook"


def _request(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode()
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    request.json = AsyncMock(return_value=payload)
    request.headers = {}
    return request


def _bot_service(bot: MagicMock | None) -> MagicMock:
    return MagicMock(find_active=AsyncMock(return_value=bot))


@pytest.fixture(autouse=True)
def _adapter():
    """A registered Slack adapter: unit tests run without app startup, which is
    where the real registry is filled."""
    adapter = MagicMock()
    adapter.verify_webhook_signature.return_value = True
    with patch(f"{_MODULE}.get_adapter", return_value=adapter):
        yield adapter


class TestVerification:
    async def test_an_unknown_bot_answers_empty_success(self):
        """200 with nothing: a prober learns only that the endpoint exists,
        which the URL already says."""
        response = await slack_events(
            uuid.uuid4(), _request({"type": "event_callback"}), _bot_service(None)
        )

        assert response.status_code == 200

    async def test_a_bot_without_a_signing_secret_refuses_and_names_the_fix(self):
        bot = MagicMock()

        with (
            patch(f"{_MODULE}.unseal_slack_signing_secret", return_value=None),
            pytest.raises(HTTPException) as refused,
        ):
            await slack_events(
                uuid.uuid4(), _request({"type": "event_callback"}), _bot_service(bot)
            )

        assert refused.value.status_code == 500
        assert "signing secret" in refused.value.detail

    async def test_a_bad_signature_is_refused_before_anything_is_processed(self):
        bot = MagicMock()
        adapter = MagicMock()
        adapter.verify_webhook_signature.return_value = False

        with (
            patch(f"{_MODULE}.unseal_slack_signing_secret", return_value="bot-secret"),
            patch(f"{_MODULE}.get_adapter", return_value=adapter),
            pytest.raises(HTTPException) as refused,
        ):
            await slack_events(
                uuid.uuid4(), _request({"type": "event_callback"}), _bot_service(bot)
            )

        assert refused.value.status_code == 403
        # Verified with the bot's own secret, not anything deployment-wide.
        assert adapter.verify_webhook_signature.call_args.args[1] == "bot-secret"

    async def test_a_redelivery_is_scheduled_because_the_first_attempt_may_have_failed(
        self, _adapter
    ):
        """`x-slack-retry-num` says Slack is redelivering, not that the first
        attempt did any work: `reason=http_error` means it received a non-2xx,
        so this route raised before `spawn` and nothing was ever scheduled.
        Answering 200 on the header alone would drop the only delivery left that
        could run the message. The Redis claim in the router is what refuses a
        genuine duplicate, and it knows the difference (#167)."""
        bot = MagicMock()
        _adapter.parse_incoming.return_value = MagicMock()
        request = _request({"type": "event_callback", "event": {"type": "message"}})
        request.headers = {"x-slack-retry-num": "1", "x-slack-retry-reason": "http_error"}

        # The coroutine is closed rather than dropped: nothing awaits it once
        # `spawn` is a mock, and an un-awaited coroutine is a warning per test.
        with (
            patch(f"{_MODULE}.unseal_slack_signing_secret", return_value="bot-secret"),
            patch(f"{_MODULE}.spawn", side_effect=lambda coro, **_: coro.close()) as spawn,
        ):
            response = await slack_events(uuid.uuid4(), request, _bot_service(bot))

        assert response.status_code == 200
        spawn.assert_called_once()

    async def test_a_redelivered_challenge_still_echoes_the_challenge(self):
        """URL verification is answered on its own terms whatever the retry
        headers say - a challenge swallowed as a redelivery leaves the endpoint
        unverifiable with nothing on screen to explain it."""
        bot = MagicMock()
        request = _request({"type": "url_verification", "challenge": "abc123"})
        request.headers = {"x-slack-retry-num": "2"}

        with patch(f"{_MODULE}.unseal_slack_signing_secret", return_value="bot-secret"):
            answer = await slack_events(uuid.uuid4(), request, _bot_service(bot))

        assert answer == {"challenge": "abc123"}

    async def test_a_retry_header_does_not_bypass_verification(self):
        """A redelivery is verified like any other request - the header is read
        after the signature, so a forged one buys nothing."""
        bot = MagicMock()
        adapter = MagicMock()
        adapter.verify_webhook_signature.return_value = False
        request = _request({"type": "event_callback", "event": {"type": "message"}})
        request.headers = {"x-slack-retry-num": "1"}

        with (
            patch(f"{_MODULE}.unseal_slack_signing_secret", return_value="bot-secret"),
            patch(f"{_MODULE}.get_adapter", return_value=adapter),
            pytest.raises(HTTPException) as refused,
        ):
            await slack_events(uuid.uuid4(), request, _bot_service(bot))

        assert refused.value.status_code == 403

    async def test_url_verification_echoes_the_challenge_once_verified(self):
        bot = MagicMock()

        with patch(f"{_MODULE}.unseal_slack_signing_secret", return_value="bot-secret"):
            answer = await slack_events(
                uuid.uuid4(),
                _request({"type": "url_verification", "challenge": "c123"}),
                _bot_service(bot),
            )

        assert answer == {"challenge": "c123"}
