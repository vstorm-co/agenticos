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

    async def test_url_verification_echoes_the_challenge_once_verified(self):
        bot = MagicMock()

        with patch(f"{_MODULE}.unseal_slack_signing_secret", return_value="bot-secret"):
            answer = await slack_events(
                uuid.uuid4(),
                _request({"type": "url_verification", "challenge": "c123"}),
                _bot_service(bot),
            )

        assert answer == {"challenge": "c123"}
