"""Web Push subscription schemas (#2097)."""

from urllib.parse import urlsplit

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

_BASE64URL = r"^[A-Za-z0-9_-]+={0,2}$"

# The push services browsers subscribe through - Chrome and every Chromium
# browser (FCM), Firefox (Mozilla's autopush), Safari (Apple), Edge on Windows
# (WNS). An endpoint is a URL a signed-in person hands the server for it to
# POST to, so it is held to these hosts rather than to "anything public": the
# library that sends connects by name, and a name checked as public here could
# answer with a private address there.
PUSH_SERVICE_SUFFIXES = (
    ".googleapis.com",
    ".services.mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
)


def push_endpoint(url: str) -> str:
    """A browser's push endpoint, or `ValueError` for anything else."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("A push endpoint is an https address of a browser's push service.")
    if not any(host.endswith(suffix) for suffix in PUSH_SERVICE_SUFFIXES):
        raise ValueError("That is not a push service this deployment sends to.")
    return url


class PushSubscriptionKeys(BaseSchema):
    p256dh: str = Field(min_length=1, max_length=128, pattern=_BASE64URL)
    auth: str = Field(min_length=1, max_length=64, pattern=_BASE64URL)


class PushSubscriptionCreate(BaseSchema):
    """What a browser's `PushSubscription.toJSON()` holds, less its expiry."""

    endpoint: str = Field(max_length=2048)
    keys: PushSubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def _a_push_service(cls, value: str) -> str:
        return push_endpoint(value)


class PushSubscriptionDelete(BaseSchema):
    endpoint: str = Field(max_length=2048)


class PushKeyRead(BaseSchema):
    """The deployment's VAPID public key, as `pushManager.subscribe` takes it."""

    public_key: str


class PushTestRead(BaseSchema):
    """How a test push went, by browser."""

    sent: int
    gone: int
    failed: int
