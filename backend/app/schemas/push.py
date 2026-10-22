"""Web Push subscription schemas (#2097)."""

from urllib.parse import urlsplit

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

_BASE64URL = r"^[A-Za-z0-9_-]+={0,2}$"


def push_endpoint(url: str) -> str:
    """A push endpoint's shape: https, no credentials in it, the default port.

    Where it points is checked when it is stored and again on every send
    (`app.services.web_push`): a browser's push service, or a UnifiedPush
    distributor such as a company's own ntfy server - anything public, and
    nothing inside the deployment's network.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("A push endpoint is an https address with no credentials in it.")
    if parts.port not in (None, 443):
        raise ValueError("A push endpoint is served on the https port.")
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
