"""Authentication on raw bytes, before JSON parsing or subscriber dispatch."""

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping

from app.core.exceptions import BadRequestError
from app.schemas.event_source import SourceAuth, SourceCredentials
from app.services import trigger_events


def standard_key(secret: str) -> bytes:
    """Decode Standard Webhooks' optional whsec_ prefix and base64 symmetric key."""
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BadRequestError(message="Standard Webhooks requires a base64 symmetric key") from exc
    if not 24 <= len(key) <= 64:
        raise BadRequestError(
            message="Standard Webhooks requires between 24 and 64 random key bytes"
        )
    return key


def verify_source(
    provider: str,
    auth: SourceAuth,
    credentials: SourceCredentials,
    *,
    body: bytes,
    headers: Mapping[str, str],
    url: str,
    now: float | None = None,
) -> bool:
    """A malformed header is a refusal; no credential is returned or logged."""
    moment = time.time() if now is None else now
    secret = credentials.secret.get_secret_value() if credentials.secret else ""
    if auth.method == "provider":
        return trigger_events.verify_signature(
            provider, secret=secret, body=body, headers=headers, url=url, now=moment
        )
    if auth.method == "basic":
        if not credentials.username or not credentials.password:
            return False
        value = (
            f"{credentials.username.get_secret_value()}:{credentials.password.get_secret_value()}"
        )
        scheme, _, token = headers.get("authorization", "").encode().partition(b" ")
        return scheme.lower() == b"basic" and secrets.compare_digest(
            base64.b64encode(value.encode()), token.lstrip(b" ")
        )
    if auth.method == "api_key":
        return secrets.compare_digest(
            (auth.signature_prefix + secret).encode(), headers.get(auth.header_name, "").encode()
        )
    if auth.method == "standard_webhooks":
        stamp = headers.get("webhook-timestamp", "")
        identifier = headers.get("webhook-id", "")
        if not identifier or len(stamp) > 16 or not stamp.isascii() or not stamp.isdigit():
            return False
        if abs(moment - int(stamp)) > trigger_events.TIMESTAMP_TOLERANCE_SECONDS:
            return False
        signed = identifier.encode() + b"." + stamp.encode() + b"." + body
        expected = base64.b64encode(hmac.new(standard_key(secret), signed, hashlib.sha256).digest())
        return any(
            hmac.compare_digest(expected, value[3:].encode())
            for value in headers.get("webhook-signature", "").split()
            if value.startswith("v1,")
        )
    signed = body
    if auth.legacy:
        stamp = headers.get("x-signature-timestamp", "").strip()
        if stamp:
            if (
                len(stamp) > 16
                or not stamp.isascii()
                or not stamp.isdigit()
                or abs(moment - int(stamp)) > trigger_events.TIMESTAMP_TOLERANCE_SECONDS
            ):
                return False
            signed = stamp.encode() + b"." + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    if auth.encoding == "hex":
        encoded = digest.hex()
    elif auth.encoding == "base64":
        encoded = base64.b64encode(digest).decode()
    else:
        encoded = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return hmac.compare_digest(
        (auth.signature_prefix + encoded).encode(), headers.get(auth.header_name, "").encode()
    )
