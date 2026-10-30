"""Push schemas: Web Push subscriptions and iPhones' APNs tokens and key (#2097)."""

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr, field_validator

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
    """How a test push went, by browser and iPhone."""

    sent: int
    gone: int
    failed: int


ApnsEnvironment = Literal["production", "sandbox"]


class ApnsKeyUpdate(BaseSchema):
    """The organization's APNs key, as Apple's developer account hands it out:
    the `.p8` file's contents, its key ID, the team ID, and the app's bundle
    identifier the messages are for."""

    key_id: str = Field(pattern=r"^[A-Z0-9]{10}$")
    team_id: str = Field(pattern=r"^[A-Z0-9]{10}$")
    topic: str = Field(min_length=1, max_length=155, pattern=r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
    environment: ApnsEnvironment = "production"
    private_key: SecretStr = Field(min_length=1, max_length=4096)


class ApnsRead(BaseSchema):
    """Whether iPhones can be pushed to, and with whose key - never the key."""

    configured: bool
    key_id: str | None = None
    team_id: str | None = None
    topic: str | None = None
    environment: ApnsEnvironment | None = None


class ApnsDeviceCreate(BaseSchema):
    """The token the iOS app received from APNs, hex."""

    token: str = Field(min_length=64, max_length=200, pattern=r"^[0-9a-f]+$")


class PushPreferencesUpdate(BaseSchema):
    """Per sign-in, applied before a payload leaves for Apple or a distributor."""

    hide_previews: bool = False
    muted_conversations: list[UUID] = Field(default_factory=list, max_length=500)


class PushPreferencesRead(PushPreferencesUpdate):
    """The current sign-in also binds native notification taps to this connection."""

    session_id: UUID | None = None


class PushFocusUpdate(BaseSchema):
    conversation_id: UUID | None = None


class PushDeliveryPreferences(PushPreferencesUpdate):
    focused_conversation: UUID | None = None
    focus_until: AwareDatetime | None = None
