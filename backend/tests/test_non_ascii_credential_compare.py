"""A malformed credential is refused, not a 500 (#33).

`secrets.compare_digest` - and `hmac.compare_digest`, which is the same function -
raises `TypeError` on a non-ASCII `str`, not `False`. Each of these three checks
takes its left operand from the caller, so `{"token": "é"}` to the Mattermost
webhook, a non-ASCII `X-Slack-Signature`, or a non-ASCII API key was a logged 500
- a free log-flooding primitive on an unauthenticated endpoint - rather than a
refusal. Comparing `.encode()`d bytes refuses it in constant time instead.

`.encode()` closes one door and opens another: a lone surrogate survives
`json.loads` (`{"token": "\\ud800"}`) and a bare UTF-8 `.encode()` on it raises
`UnicodeEncodeError` - the same 500. `encode_untrusted` uses `surrogatepass`, so
every attacker-controlled value reaches the compare as bytes that cannot match a
real secret.
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
# Survives json.loads as a lone surrogate; a bare UTF-8 encode raises on it.
_LONE_SURROGATE = "\ud800"


def test_a_non_ascii_mattermost_token_is_refused_rather_than_crashing() -> None:
    result = MattermostAdapter().verify_webhook_signature(
        {}, "shared-token", f'{{"token": "{_NON_ASCII}"}}'
    )
    assert result is False


def test_a_lone_surrogate_mattermost_token_is_refused_rather_than_crashing() -> None:
    result = MattermostAdapter().verify_webhook_signature(
        {}, "shared-token", '{"token": "\\ud800"}'
    )
    assert result is False


def test_a_non_ascii_slack_signature_is_refused_rather_than_crashing() -> None:
    headers = {
        "x-slack-request-timestamp": str(int(time.time())),
        "x-slack-signature": _NON_ASCII,
    }
    assert SlackAdapter().verify_webhook_signature(headers, "signing-secret", "body") is False


def test_a_lone_surrogate_slack_signature_is_refused_rather_than_crashing() -> None:
    headers = {
        "x-slack-request-timestamp": str(int(time.time())),
        "x-slack-signature": _LONE_SURROGATE,
    }
    assert SlackAdapter().verify_webhook_signature(headers, "signing-secret", "body") is False


def test_a_lone_surrogate_slack_body_is_refused_rather_than_crashing() -> None:
    """The body is folded into the signed base string, so it is encoded too."""
    headers = {
        "x-slack-request-timestamp": str(int(time.time())),
        "x-slack-signature": "v0=deadbeef",
    }
    assert (
        SlackAdapter().verify_webhook_signature(headers, "signing-secret", _LONE_SURROGATE) is False
    )


async def test_a_non_ascii_api_key_is_refused_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "API_KEY", "the-real-api-key")
    with pytest.raises(AuthorizationError):
        await verify_api_key(_NON_ASCII)


async def test_a_lone_surrogate_api_key_is_refused_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "API_KEY", "the-real-api-key")
    with pytest.raises(AuthorizationError):
        await verify_api_key(_LONE_SURROGATE)
