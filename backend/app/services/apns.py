"""Push to iPhones through Apple's push service, with the organization's own key (#2097).

A company signs its own build of the iOS app, and Apple delivers a push only
when it is signed with a key of the developer account the app was signed with.
So the key is the company's: an administrator sets it once - the `.p8` file,
its key ID, the team ID and the app's bundle identifier - and it is sealed in
the vault beside the Web Push key (`DeploymentSettingsService.set_apns_key`).
Without one, iPhones get no push, and the app does not offer it.

The app hands the console a device token once the person allows
notifications; `register` keeps it. `send` signs a short-lived provider token
(ES256, reused for most of an hour, as Apple asks) and posts one message per
iPhone over HTTP/2. A token Apple says is gone is forgotten; any other refusal
counts as failed, for the delivery sweep to retry.
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

import httpx
import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.vault import VaultScope, unseal
from app.db.models.apns_device import ApnsDevice
from app.repositories import apns_device as device_repo
from app.repositories import deployment_settings as deployment_repo
from app.schemas.push import ApnsRead
from app.services.web_push import PushMessage, PushOutcome

logger = logging.getLogger(__name__)

HOSTS = {
    "production": "https://api.push.apple.com",
    "sandbox": "https://api.sandbox.push.apple.com",
}
# Per iPhone. The delivery sweep's own timeout bounds the whole send.
SEND_TIMEOUT_SECONDS = 10
# How long APNs keeps a message for an iPhone that is off: a day, as Web Push.
TTL_SECONDS = 24 * 60 * 60
# Apple refuses a provider token older than an hour and one renewed more often
# than every twenty minutes; fifty minutes sits inside both.
PROVIDER_TOKEN_SECONDS = 50 * 60
# Apple saying this token is no use: the app was removed (410), or the token is
# not one of this topic's or this environment's (400). Nothing to retry.
GONE_REASONS = frozenset({"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"})
STALE_PROVIDER_TOKEN = frozenset({"ExpiredProviderToken", "InvalidProviderToken"})


@dataclass(frozen=True)
class ApnsAnswer:
    """APNs' answer to one message: the HTTP status, and Apple's `reason`."""

    status: int
    reason: str | None


class ApnsTransport(Protocol):
    async def post(self, url: str, *, headers: dict[str, str], body: bytes) -> ApnsAnswer:
        """Post one message over HTTP/2 and read Apple's answer.

        Raises `httpx.HTTPError` when no answer came - the message may or may
        not have been accepted.
        """
        ...


class _HttpxTransport:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def post(self, url: str, *, headers: dict[str, str], body: bytes) -> ApnsAnswer:
        response = await self._client.post(url, headers=headers, content=body)
        reason: str | None = None
        if response.status_code != 200 and response.content:
            try:
                answer = response.json()
            except ValueError:
                answer = None
            if isinstance(answer, dict) and isinstance(answer.get("reason"), str):
                reason = answer["reason"]
        return ApnsAnswer(status=response.status_code, reason=reason)


@asynccontextmanager
async def http2_transport() -> AsyncGenerator[ApnsTransport]:
    """One HTTP/2 connection for a send's messages; APNs accepts nothing else."""
    async with httpx.AsyncClient(http2=True, timeout=SEND_TIMEOUT_SECONDS) as client:
        yield _HttpxTransport(client)


@dataclass(frozen=True)
class _Key:
    """The organization's key, opened, with whose it is."""

    private_key: str
    key_id: str
    team_id: str
    topic: str
    sandbox: bool


# The provider token by (team, key): signed once and reused for its lifetime
# across sends, because Apple throttles a sender that signs a new one per
# message (`TooManyProviderTokenUpdates`).
_provider_tokens: dict[tuple[str, str], tuple[str, float]] = {}


def _provider_token(key: _Key, now: float) -> str:
    cached = _provider_tokens.get((key.team_id, key.key_id))
    if cached is not None and now - cached[1] < PROVIDER_TOKEN_SECONDS:
        return cached[0]
    token = jwt.encode(
        {"iss": key.team_id, "iat": int(now)},
        key.private_key,
        algorithm="ES256",
        headers={"kid": key.key_id},
    )
    _provider_tokens[(key.team_id, key.key_id)] = (token, now)
    return token


def check_key(pem: str) -> None:
    """Refuse anything that is not an APNs key: an EC P-256 private key in PEM."""
    try:
        key = load_pem_private_key(pem.encode(), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise BadRequestError(message="That is not an APNs key: paste the .p8 file.") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise BadRequestError(message="An APNs key is an EC P-256 key (a .p8 file).")


class ApnsService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        connect: Callable[[], AbstractAsyncContextManager[ApnsTransport]] = http2_transport,
    ):
        self.db = db
        self._connect = connect

    async def _key(self) -> _Key | None:
        row = await deployment_repo.get(self.db)
        if (
            row is None
            or row.apns_private_key is None
            or row.apns_key_id is None
            or row.apns_team_id is None
            or row.apns_topic is None
        ):
            return None
        private_key = unseal(
            row.apns_private_key,
            scope=VaultScope.deployment(),
            key_version=row.apns_key_version or 1,
        )
        return _Key(
            private_key=private_key,
            key_id=row.apns_key_id,
            team_id=row.apns_team_id,
            topic=row.apns_topic,
            sandbox=bool(row.apns_sandbox),
        )

    async def read(self) -> ApnsRead:
        """Whose key, if any - never the key itself."""
        row = await deployment_repo.get(self.db)
        if row is None or row.apns_private_key is None:
            return ApnsRead(configured=False)
        return ApnsRead(
            configured=True,
            key_id=row.apns_key_id,
            team_id=row.apns_team_id,
            topic=row.apns_topic,
            environment="sandbox" if row.apns_sandbox else "production",
        )

    async def register(self, user_id: uuid.UUID, token: str) -> None:
        """Push to this iPhone from now on. Refused where there is no key to push with."""
        if not (await self.read()).configured:
            raise BadRequestError(message="This deployment has no APNs key, so no iPhone push.")
        await device_repo.upsert(self.db, user_id=user_id, token=token)

    async def unregister(self, user_id: uuid.UUID, token: str) -> None:
        if not await device_repo.delete_for_user(self.db, user_id=user_id, token=token):
            raise NotFoundError(message="This iPhone is not registered for push.")

    async def has_devices(self, user_id: uuid.UUID) -> bool:
        return bool(await device_repo.list_for_user(self.db, user_id))

    async def subscribed(self, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Who of these people has an iPhone to push to - nobody, without a key."""
        if not (await self.read()).configured:
            return set()
        return await device_repo.subscribed(self.db, user_ids)

    async def send(self, user_id: uuid.UUID, message: PushMessage) -> PushOutcome:
        """Push to every iPhone the person registered; none without a key."""
        devices = await device_repo.list_for_user(self.db, user_id)
        if not devices:
            return PushOutcome(sent=0, gone=0, failed=0)
        key = await self._key()
        if key is None:
            return PushOutcome(sent=0, gone=0, failed=0)
        body = json.dumps(
            {
                "aps": {
                    "alert": {"title": message.title, "body": message.body},
                    "sound": "default",
                    "thread-id": "agenticos",
                },
                "url": message.url,
            }
        ).encode()
        sent = gone = failed = 0
        async with self._connect() as transport:
            for device in devices:
                outcome = await self._send_one(transport, key, device, message.tag, body)
                if outcome == "sent":
                    sent += 1
                elif outcome == "gone":
                    gone += 1
                else:
                    failed += 1
        return PushOutcome(sent=sent, gone=gone, failed=failed)

    async def _send_one(
        self,
        transport: ApnsTransport,
        key: _Key,
        device: ApnsDevice,
        tag: str,
        body: bytes,
    ) -> Literal["sent", "gone", "failed"]:
        now = time.time()
        headers = {
            "authorization": f"bearer {_provider_token(key, now)}",
            "apns-topic": key.topic,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "apns-expiration": str(int(now) + TTL_SECONDS),
            # A notification sent again replaces the one already shown.
            "apns-collapse-id": tag[:64],
        }
        host = HOSTS["sandbox" if key.sandbox else "production"]
        try:
            answer = await transport.post(
                f"{host}/3/device/{device.token}", headers=headers, body=body
            )
        except httpx.HTTPError:
            logger.warning("apns_unreachable", extra={"device_id": str(device.id)})
            return "failed"
        if answer.status == 200:
            await device_repo.mark_sent(self.db, device.id, datetime.now(UTC))
            return "sent"
        if answer.status == 410 or answer.reason in GONE_REASONS:
            await device_repo.delete_by_id(self.db, device.id)
            return "gone"
        if answer.reason in STALE_PROVIDER_TOKEN:
            # Signed again on the next send, rather than refused for an hour.
            _provider_tokens.pop((key.team_id, key.key_id), None)
        logger.warning(
            "apns_refused",
            extra={"device_id": str(device.id), "status": answer.status, "reason": answer.reason},
        )
        return "failed"
