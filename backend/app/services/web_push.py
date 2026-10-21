"""Web Push to the browsers and installed PWAs a person turned notifications on in (#2097).

A message is encrypted to the browser's keys (RFC 8291) and signed with this
deployment's VAPID key (RFC 8292), which is made the first time anything needs
it and kept in the vault: nobody configures Web Push. The notification center
queues a `push` delivery like an email one, and the delivery sweep sends it
through `send`; the console's settings page subscribes a browser, and can ask
for a test.
"""

import asyncio
import base64
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException, webpush_async
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.vault import VaultScope, current_key_version, seal, unseal
from app.repositories import deployment_settings as deployment_repo
from app.repositories import push_subscription as push_repo
from app.schemas.push import PushSubscriptionCreate

logger = logging.getLogger(__name__)

# How long a push service keeps a message for a browser that is offline. A
# notification about a run is stale after a day; one that arrives a week late
# is noise.
TTL_SECONDS = 24 * 60 * 60
# Per browser. The delivery sweep's own timeout bounds the whole send.
SEND_TIMEOUT_SECONDS = 10
# The push service saying this browser is gone - unsubscribed, or its data
# cleared. Nothing to retry; the subscription goes.
GONE = frozenset({404, 410})


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _new_key() -> tuple[str, str]:
    """A P-256 key pair as Web Push spells it: the private scalar and the
    uncompressed public point, both base64url."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return _b64url(private), _b64url(public)


def _subject() -> str:
    """Who the push service may contact about this sender (RFC 8292 `sub`):
    the console's address where it is public, the sending address otherwise."""
    if settings.FRONTEND_URL.startswith("https://"):
        return settings.FRONTEND_URL
    return f"mailto:{settings.EMAIL_FROM}"


@dataclass(frozen=True)
class PushMessage:
    """What a browser shows: the service worker draws it and opens `url` on a click."""

    title: str
    body: str
    url: str
    tag: str


@dataclass(frozen=True)
class PushOutcome:
    """How one send went, by browser."""

    sent: int
    gone: int
    failed: int


class WebPushService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _signing_key(self) -> tuple[str, str]:
        """The deployment's VAPID private and public key, made on first use."""
        row = await deployment_repo.get(self.db)
        if row is None or row.vapid_private_key is None or row.vapid_public_key is None:
            private, public = _new_key()
            version = current_key_version()
            sealed = seal(private, scope=VaultScope.deployment(), key_version=version)
            row = await deployment_repo.claim_vapid_key(
                self.db,
                private_key=sealed.ciphertext,
                public_key=public,
                key_version=sealed.key_version,
            )
        if row.vapid_private_key is None or row.vapid_public_key is None:  # pragma: no cover
            # The claim writes both or neither; a row that still has none is a
            # database that dropped the write, not a state this code makes.
            raise RuntimeError("The Web Push key was not stored.")
        private = unseal(
            row.vapid_private_key,
            scope=VaultScope.deployment(),
            key_version=row.vapid_key_version or 1,
        )
        return private, row.vapid_public_key

    async def public_key(self) -> str:
        """What a browser subscribes with (`applicationServerKey`)."""
        _, public = await self._signing_key()
        return public

    async def subscribe(
        self, user_id: uuid.UUID, subscription: PushSubscriptionCreate, *, user_agent: str | None
    ) -> None:
        await push_repo.upsert(
            self.db,
            user_id=user_id,
            endpoint=subscription.endpoint,
            p256dh=subscription.keys.p256dh,
            auth=subscription.keys.auth,
            user_agent=user_agent,
        )

    async def unsubscribe(self, user_id: uuid.UUID, endpoint: str) -> None:
        if not await push_repo.delete_for_user(self.db, user_id=user_id, endpoint=endpoint):
            raise NotFoundError(message="This browser is not subscribed.")

    async def send(self, user_id: uuid.UUID, message: PushMessage) -> PushOutcome:
        """Push to every browser the person subscribed.

        A browser the push service says is gone is forgotten; any other refusal
        counts as failed, for the caller to retry or report.
        """
        subscriptions = await push_repo.list_for_user(self.db, user_id)
        if not subscriptions:
            return PushOutcome(sent=0, gone=0, failed=0)
        private, _ = await self._signing_key()
        signer = Vapid.from_string(private_key=private)
        data = json.dumps(
            {"title": message.title, "body": message.body, "url": message.url, "tag": message.tag}
        )
        sent = gone = failed = 0
        for subscription in subscriptions:
            try:
                await asyncio.wait_for(
                    webpush_async(
                        subscription_info={
                            "endpoint": subscription.endpoint,
                            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                        },
                        data=data,
                        vapid_private_key=signer,
                        vapid_claims={"sub": _subject()},
                        ttl=TTL_SECONDS,
                    ),
                    timeout=SEND_TIMEOUT_SECONDS,
                )
            except WebPushException as exc:
                if exc.status_code in GONE:
                    await push_repo.delete_by_id(self.db, subscription.id)
                    gone += 1
                    continue
                logger.warning(
                    "web_push_refused",
                    extra={"subscription_id": str(subscription.id), "status": exc.status_code},
                )
                failed += 1
                continue
            except TimeoutError:
                logger.warning(
                    "web_push_timed_out", extra={"subscription_id": str(subscription.id)}
                )
                failed += 1
                continue
            await push_repo.mark_sent(self.db, subscription.id, datetime.now(UTC))
            sent += 1
        return PushOutcome(sent=sent, gone=gone, failed=failed)

    async def send_test(self, user_id: uuid.UUID, *, app_name: str) -> PushOutcome:
        """A push to the caller's own browsers, from the settings page."""
        if not await push_repo.list_for_user(self.db, user_id):
            raise NotFoundError(message="No browser of yours is subscribed to push yet.")
        return await self.send(
            user_id,
            PushMessage(
                title=app_name,
                body="Push works. This is what a notification from your agents looks like.",
                url="/settings/notifications",
                tag="push-test",
            ),
        )
