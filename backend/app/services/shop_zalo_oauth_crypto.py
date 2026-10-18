"""Signed OAuth state for Shop Zalo connect (D3 B65)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import BadRequestError


def _fernet() -> Fernet:
    raw = (settings.SHOP_ZALO_OAUTH_STATE_SECRET or settings.SECRET_KEY or "").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def sign_shop_zalo_oauth_state(payload: dict[str, Any]) -> str:
    body = dict(payload)
    if "exp" not in body:
        body["exp"] = int(time.time()) + int(settings.SHOP_AI_ZALO_OAUTH_STATE_TTL_SEC)
    token = _fernet().encrypt(json.dumps(body, separators=(",", ":")).encode())
    return token.decode()


def verify_shop_zalo_oauth_state(token: str) -> dict[str, Any]:
    try:
        raw = _fernet().decrypt(str(token or "").strip().encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise BadRequestError(message="Invalid OAuth state", details={"field": "state"}) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequestError(message="Invalid OAuth state", details={"field": "state"}) from exc
    if not isinstance(data, dict):
        raise BadRequestError(message="Invalid OAuth state", details={"field": "state"})
    exp = int(data.get("exp") or 0)
    if exp < int(time.time()):
        raise BadRequestError(message="OAuth state expired", details={"field": "state"})
    return data
