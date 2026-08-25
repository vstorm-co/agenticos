"""A non-ASCII credential is refused, not a 500 (#33).

`secrets.compare_digest` - and `hmac.compare_digest`, which is the same function -
raises `TypeError` on a non-ASCII `str`, not `False`. Each of these three checks
takes its left operand from the caller, so `{"token": "é"}` to the Mattermost
webhook, a non-ASCII `X-Slack-Signature`, or a non-ASCII API key was a logged 500
- a free log-flooding primitive on an unauthenticated endpoint - rather than a
refusal. Comparing `.encode()`d bytes refuses it in constant time instead.
"""

from __future__ import annotations

import time

import pytest

from app.api.deps import verify_api_key
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter

pytestmark = pytest.mark.anyio

_NON_ASCII = "café-éé"


def test_a_non_ascii_mattermost_token_is_refused_rather_than_crashing() -> None:
    result = MattermostAdapter().verify_webhook_signature(
        {}, "shared-token", f'{{"token": "{_NON_ASCII}"}}'
    )
    assert result is False


def test_a_non_ascii_slack_signature_is_refused_rather_than_crashing() -> None:
    headers = {
        "x-slack-request-timestamp": str(int(time.time())),
        "x-slack-signature": _NON_ASCII,
    }
    assert SlackAdapter().verify_webhook_signature(headers, "signing-secret", "body") is False


async def test_a_non_ascii_api_key_is_refused_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "API_KEY", "the-real-api-key")
    with pytest.raises(AuthorizationError):
        await verify_api_key(_NON_ASCII)
