"""B69 — Messenger channel adapter."""

from __future__ import annotations

import hashlib
import hmac

from app.services.channels.messenger import MessengerAdapter


def test_parse_page_messaging_text() -> None:
    adapter = MessengerAdapter()
    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": "psid-99"},
                        "message": {"text": "Xin chao shop", "mid": "m.1"},
                    }
                ]
            }
        ],
    }
    incoming = adapter.parse_incoming(payload, bot_id="bot-uuid")
    assert incoming is not None
    assert incoming.platform == "messenger"
    assert incoming.platform_user_id == "psid-99"
    assert incoming.text == "Xin chao shop"


def test_verify_hub_signature() -> None:
    adapter = MessengerAdapter()
    secret = "meta-app-secret"
    body = '{"object":"page"}'
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": f"sha256={digest}"}
    assert adapter.verify_webhook_signature(headers, secret, body=body)
