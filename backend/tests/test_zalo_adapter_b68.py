"""B68 — Zalo channel adapter."""

from __future__ import annotations

import hashlib
import json

from app.services.channels.zalo import ZaloAdapter


def test_parse_user_send_text() -> None:
    adapter = ZaloAdapter()
    payload = {
        "event_name": "user_send_text",
        "sender": {"id": "user-123", "name": "Resident A"},
        "message": {"text": "Tra don hang giup toi", "msg_id": "m1"},
    }
    incoming = adapter.parse_incoming(payload, bot_id="bot-uuid")
    assert incoming is not None
    assert incoming.platform == "zalo"
    assert incoming.platform_user_id == "user-123"
    assert incoming.text == "Tra don hang giup toi"


def test_verify_webhook_signature_mac_prefix() -> None:
    adapter = ZaloAdapter()
    app_id = "123456"
    secret = "oa-secret-key"
    timestamp = "1710000000123"
    body_dict = {
        "app_id": app_id,
        "event_name": "user_send_text",
        "timestamp": timestamp,
    }
    body = json.dumps(body_dict, separators=(",", ":"))
    mac_input = f"{app_id}{body}{timestamp}{secret}"
    signature = f"mac={hashlib.sha256(mac_input.encode()).hexdigest()}"

    headers = {"X-ZEvent-Signature": signature}
    assert adapter.verify_webhook_signature(headers, secret, body=body)
