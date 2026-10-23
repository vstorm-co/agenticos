"""Reaching a person's own computer: which ones are connected, and a call to one.

**The app dials out; the server never dials in.** A laptop sits behind NAT and a
firewall, so the desktop app holds one WebSocket open to the API (`serve`) and
everything the server wants from that computer travels down it. The socket is held
by whichever API host the app reached, while the run that needs the computer may be
on another host or in the worker - so a call is routed through Redis rather than
through the socket object: the run publishes to the device's inbox channel, the
host holding the socket relays it, and the answer comes back on a channel named for
the call. A publish nobody received means no host holds that device: the computer
is offline, and the caller learns it at once rather than after a timeout.

**Presence is a key with a lifetime.** The serving host refreshes it while the
socket lives, so a host that dies takes its devices offline within a minute rather
than leaving them listed for ever. A device is a session - the app's own, from
pairing - so the Devices screen's "Disconnect" ends it like any other.
"""

import contextlib
import logging
import secrets
from collections.abc import AsyncGenerator, Mapping
from typing import Any, Protocol
from uuid import UUID

import anyio
from pydantic import BaseModel, ValidationError
from redis.asyncio.client import PubSub
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.exceptions import AuthorizationError
from app.core.security import verify_token
from app.db.session import get_db_context
from app.repositories import session_repo
from app.services.device_hub._protocol import (
    APP_FRAME,
    MAX_FRAME_BYTES,
    Call,
    Cancel,
    Capabilities,
    Hello,
    Result,
    new_call_id,
)
from app.services.device_hub.exceptions import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
)

logger = logging.getLogger(__name__)

PRESENCE_TTL_SECONDS = 90
"""How long a device stays listed after its host last vouched for it."""

HEARTBEAT_SECONDS = 30
"""How often the serving host renews a device's presence - well inside its lifetime."""

_redis: RedisClient | None = None


class _Disconnected(Exception):
    """The computer's session ended while its socket was open; the socket is closed."""


class Socket(Protocol):
    """What the hub needs of the app's WebSocket - Starlette's, or a test's."""

    async def receive(self) -> Mapping[str, Any]: ...

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class Device(BaseModel):
    """One computer an app is connected from, as the hub records it."""

    session_id: UUID
    user_id: UUID
    platform: str
    version: str = ""
    capabilities: Capabilities = Capabilities()
    connection: str = ""
    """This socket's own id, so a reconnect's presence is not removed by the old socket."""


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the API's lifespan and by the worker, because a run asking for a
    computer may be in either and both must reach the host holding its socket.
    """
    global _redis
    _redis = redis


_connecting = anyio.Lock()


async def _require() -> RedisClient:
    """The Redis to route through, connected on first use in a process nobody configured.

    The API's lifespan hands one over; the worker, where a trigger's run may need
    the person's computer, does not - so a call there connects its own, once, and
    keeps it for the life of the process, as the trigger dedupe does.
    """
    global _redis
    async with _connecting:
        if _redis is None:
            client = RedisClient()
            await client.connect()
            _redis = client
    return _redis


def _presence_key(session_id: UUID) -> str:
    return f"devicehub:device:{session_id}"


def _user_key(user_id: UUID) -> str:
    return f"devicehub:user:{user_id}"


def _inbox(session_id: UUID) -> str:
    return f"devicehub:to:{session_id}"


def _reply(call_id: str) -> str:
    return f"devicehub:reply:{call_id}"


async def connected(user_id: UUID) -> list[Device]:
    """The person's computers with an app connected now, the most recent first.

    A session id left in the person's index after its presence lapsed - a host
    that died - is dropped from the index on the way.
    """
    redis = await _require()
    members = sorted(await redis.raw.smembers(_user_key(user_id)))
    if not members:
        return []
    found: list[Device] = []
    for raw_id in members:
        value = await redis.get(_presence_key(UUID(str(raw_id))))
        if value is None:
            await redis.raw.srem(_user_key(user_id), raw_id)
            continue
        found.append(Device.model_validate_json(value))
    return found


WAIT_POLL_SECONDS = 2.0
"""How often a parked run looks for its computer again."""


async def wait_for(user_id: UUID, device_id: UUID | None, *, timeout: float) -> Device | None:
    """The computer once it is connected, waiting up to `timeout` for it to come back.

    A laptop that slept, or an app that was closed for a moment, reconnects with
    the same session, so a run parked on it carries on in the same folder.
    `device_id` of `None` takes whichever of the person's computers connects.
    """

    async def find() -> Device | None:
        devices = await connected(user_id)
        return next((d for d in devices if device_id is None or d.session_id == device_id), None)

    found = await find()
    if found is not None or timeout <= 0:
        return found
    with anyio.move_on_after(timeout):
        while found is None:
            await anyio.sleep(WAIT_POLL_SECONDS)
            found = await find()
    return found


async def call(
    session_id: UUID, op: str, args: dict[str, Any], *, timeout: float
) -> dict[str, Any]:
    """Run one operation on the computer `session_id` is signed in from.

    The reply channel is subscribed before the call is published, so an answer
    that comes back faster than the subscription would have is not missed.

    Raises:
        DeviceUnavailable: No API host holds that computer's socket.
        DeviceCallTimedOut: No answer within `timeout`; the app is told to stop.
        DeviceCallFailed: The app answered with an error.
    """
    redis = await _require()
    call_id = new_call_id()
    async with _subscribed(redis, _reply(call_id)) as replies:
        delivered = await redis.raw.publish(
            _inbox(session_id), Call(id=call_id, op=op, args=args).model_dump_json()
        )
        if not delivered:
            raise DeviceUnavailable(
                message="Your computer is not connected: the AgenticOS app is closed or offline",
                details={"op": op},
            )
        try:
            with anyio.fail_after(timeout):
                result = await _first_result(replies)
        except BaseException as exc:
            # A timeout, or the run being stopped: either way the app should stop
            # the work rather than finish something nobody will read.
            with anyio.CancelScope(shield=True):
                await redis.raw.publish(_inbox(session_id), Cancel(id=call_id).model_dump_json())
            if isinstance(exc, TimeoutError):
                raise DeviceCallTimedOut(
                    message=f"Your computer did not answer within {timeout:g} seconds",
                    details={"op": op},
                ) from None
            raise
    if not result.ok:
        raise DeviceCallFailed(
            message=result.error or "Your computer refused the operation",
            details={"op": op, "kind": result.kind},
        )
    return result.value


@contextlib.asynccontextmanager
async def _subscribed(redis: RedisClient, channel: str) -> AsyncGenerator[PubSub]:
    pubsub = redis.raw.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(channel)
    try:
        yield pubsub
    finally:
        await pubsub.aclose()


async def _first_result(replies: PubSub) -> Result:
    # Subscribe confirmations are filtered out (`ignore_subscribe_messages`), so
    # whatever arrives is the answer.
    async for message in replies.listen():
        return Result.model_validate_json(message["data"])
    raise DeviceCallTimedOut(message="Your computer's connection ended before it answered")


async def serve(websocket: Socket, *, user_id: UUID, session_id: UUID, platform: str) -> None:
    """Hold one app's socket: list the computer, relay calls to it, answers from it.

    Returns when the app disconnects. The socket is already accepted. Closes with
    1011 when this process has no Redis to route through, and with 1008 on a frame
    that is not one the protocol knows - a client that speaks something else is
    not one to keep serving.
    """
    if _redis is None:
        await websocket.close(code=1011, reason="Live connections are unavailable")
        return
    redis = _redis
    device = Device(
        session_id=session_id,
        user_id=user_id,
        platform=platform,
        connection=secrets.token_hex(8),
    )
    await _announce(redis, device)
    try:
        async with (
            _subscribed(redis, _inbox(session_id)) as inbox,
            anyio.create_task_group() as tasks,
        ):
            tasks.start_soon(_relay, inbox, websocket)
            tasks.start_soon(_keep_listed, redis, device, websocket)
            await _read(websocket, redis, device)
            tasks.cancel_scope.cancel()
    except* _Disconnected:
        pass
    finally:
        with anyio.CancelScope(shield=True):
            await _withdraw(redis, device)


async def _announce(redis: RedisClient, device: Device) -> None:
    await redis.set(
        _presence_key(device.session_id), device.model_dump_json(), ttl=PRESENCE_TTL_SECONDS
    )
    await redis.raw.sadd(_user_key(device.user_id), str(device.session_id))
    await redis.expire(_user_key(device.user_id), PRESENCE_TTL_SECONDS * 4)


async def _keep_listed(redis: RedisClient, device: Device, websocket: Socket) -> None:
    """Renew the computer's presence while its session stays open.

    The session is checked each time: "Disconnect" on the Devices screen, a
    password change or a sign-out ends it, and the computer must stop taking
    calls within a heartbeat rather than for as long as the socket happens to
    stay up. 4403 tells the app not to reconnect.
    """
    while True:
        await anyio.sleep(HEARTBEAT_SECONDS)
        async with get_db_context() as db:
            session = await session_repo.get_by_id(db, device.session_id)
        if session is None or not session.is_active:
            await websocket.close(code=4403, reason="This computer was disconnected")
            raise _Disconnected
        await _announce(redis, device)


async def _withdraw(redis: RedisClient, device: Device) -> None:
    """Unlist the computer - unless a newer socket of the same app already relisted it."""
    current = await redis.get(_presence_key(device.session_id))
    if current is None or Device.model_validate_json(current).connection == device.connection:
        await redis.delete(_presence_key(device.session_id))
        await redis.raw.srem(_user_key(device.user_id), str(device.session_id))


async def _relay(inbox: PubSub, websocket: Socket) -> None:
    async for message in inbox.listen():
        data = message["data"]
        await websocket.send_text(data if isinstance(data, str) else data.decode())


async def _read(websocket: Socket, redis: RedisClient, device: Device) -> None:
    while True:
        received = await websocket.receive()
        if received["type"] == "websocket.disconnect":
            return
        text = received.get("text")
        if not isinstance(text, str) or len(text) > MAX_FRAME_BYTES:
            await websocket.close(code=1008, reason="Frames are JSON text within the size limit")
            return
        try:
            frame = APP_FRAME.validate_json(text)
        except ValidationError:
            await websocket.close(code=1008, reason="Not a frame this server speaks")
            return
        if isinstance(frame, Hello):
            device.version = frame.version
            device.capabilities = frame.capabilities
            await _announce(redis, device)
        elif isinstance(frame, Result):
            await redis.raw.publish(_reply(frame.id), text)


DESKTOP_PLATFORMS = frozenset({"macos", "windows", "linux"})
"""The apps that can hold a device socket: a phone runs nothing for an agent (#2097)."""


async def admit(db: AsyncSession, *, auth_token: str, user_id: UUID) -> tuple[UUID, str]:
    """The session and platform a device socket is opened for, or a refusal.

    Only a desktop app's own session may hold one: its access token names that
    session (`sid`), the session is the caller's and still open, and it was
    labelled by the app (`PUT /sessions/current/app`). A browser tab's session, an
    API key or an impersonation is not a computer of the person's.

    Raises:
        AuthorizationError: The token names no open desktop app session of the caller's.
    """
    payload = verify_token(auth_token)
    raw_sid = payload.get("sid") if payload is not None else None
    session = await session_repo.get_by_id(db, UUID(str(raw_sid))) if raw_sid else None
    if (
        session is None
        or session.user_id != user_id
        or not session.is_active
        or session.impersonator_user_id is not None
        or session.app_platform not in DESKTOP_PLATFORMS
    ):
        raise AuthorizationError(message="Only the AgenticOS desktop app can connect as a computer")
    return session.id, session.app_platform
