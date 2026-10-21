"""A browse anyone allowed can watch and take over, wherever its run executes (#2128).

A chat draws its browse from its own socket, but a run started from Slack, a
routine or the API has nobody on the other end of one - and those are exactly the
runs that meet a sign-in page with nobody there to help. So every browse also
publishes here, to Redis, under its run and call: the latest picture, what it has
done, and a queue of commands from the people watching. A console page at
`/browse/{run_id}/{call_id}` reads it, and a channel posts that address.

Redis rather than the process the browse runs in, because that process is the API
for a chat and the worker for a routine, and a person's socket lands on
whichever API instance the load balancer picked. Everything here expires an hour
after the browse last did anything: a live view is not a record, and the run's
own trace is.

**Watching is not driving.** The person the run acts for, and members who may
view runs, may watch. Only the person the run acts for, or someone who may edit
the agent, may take the browser over - what they do in it is done as the agent.
What a person types waits in the command queue only until the browse reads it,
and is never recorded: the run's history says only that somebody took over.
"""

import contextlib
import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

import anyio
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError
from redis.asyncio.client import PubSub

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.clients.redis import RedisClient
from app.core.audit import current_impersonator
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.permissions import AuthContext, Perm
from app.db.session import get_db_context
from app.repositories import agent as agent_repo
from app.repositories import member as member_repo
from app.services.access import AGENT, resolve_access
from app.services.ws_auth import authenticate_socket_key, authenticate_socket_token

logger = logging.getLogger(__name__)

TTL_SECONDS = 3600
"""How long a live view outlives the last thing its browse did."""

HISTORY_LIMIT = 500
"""How many of a browse's frames a late viewer is shown - the trace, not the pictures."""

COMMAND_LIMIT = 100
"""How many commands wait for a held browser at most. A person types and clicks far
slower than this drains; past it the oldest go, so a flood cannot grow Redis or bury
the newest `give_back` behind it."""

_NOT_FOUND_CLOSE_CODE = 4404
_FORBIDDEN_CLOSE_CODE = 4403

_redis: RedisClient | None = None


class BrowseMeta(BaseModel):
    """Who a browse belongs to, which is what decides who may see and drive it."""

    organization_id: UUID
    agent_id: UUID | None
    user_id: str | None
    """Who the run acts for, as the run names them - a user id, or none for a visitor."""

    remembers: bool = False
    """Whether the person the run acts for may keep a sign-in from it (#2129)."""

    personal: bool = False
    """A browse only its person may see: signing in to a site from Settings, where
    the pictures show them typing a password. Nobody else watches, whatever they
    may do with runs."""

    task: str
    started_at: datetime


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


async def connect_in_worker() -> None:
    """Give a worker process a Redis to publish on, once - see `change_feed`."""
    global _redis
    if _redis is not None:
        return
    client = RedisClient()
    await client.connect()
    _redis = client


def available() -> bool:
    """Whether this process can publish a live view at all - a CLI or a test cannot."""
    return _redis is not None


async def claim_slot(key: str, holder: str, *, limit: int, hold: float) -> bool:
    """Take one of `limit` places under `key` for `holder`, for at most `hold` seconds.

    A sorted set of holders scored by when their place lapses: lapsed places are
    dropped, this one is added, and if that made more than `limit` it is taken
    back. Added before counted, in one transaction, so two claims at once cannot
    both see room for one. A place outlives a process that died holding it by no
    more than `hold`.
    """
    assert _redis is not None
    now = time.time()
    async with _redis.raw.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, "-inf", now)
        pipe.zadd(key, {holder: now + hold})
        pipe.zcard(key)
        pipe.expire(key, int(hold) + 1)
        _, _, held, _ = await pipe.execute()
    if held <= limit:
        return True
    await _redis.raw.zrem(key, holder)
    return False


async def release_slot(key: str, holder: str) -> None:
    """Give back a place `claim_slot` handed out."""
    assert _redis is not None
    await _redis.raw.zrem(key, holder)


def link(run_id: str, call_id: str) -> str:
    """The console address of one browse's live view."""
    return f"{settings.FRONTEND_URL.rstrip('/')}/browse/{run_id}/{call_id}"


def _key(run_id: str, call_id: str, part: str) -> str:
    return f"browse:{run_id}:{call_id}:{part}"


async def open_view(run_id: str, call_id: str, meta: BrowseMeta) -> None:
    """Record who a browse belongs to, before its first frame. Never raises."""
    if _redis is None:
        return
    try:
        await _redis.raw.set(_key(run_id, call_id, "meta"), meta.model_dump_json(), ex=TTL_SECONDS)
    except Exception:
        logger.exception("live_browse_open_failed")


async def publish(run_id: str, call_id: str, event: BrowserEvent) -> None:
    """Keep and announce one frame of a browse. Never raises.

    A picture replaces the last one - a late viewer needs the page as it is, not a
    film of it - and everything else is appended to the trace a late viewer is
    shown. Both are announced on the browse's channel for the viewers already
    there.
    """
    if _redis is None:
        return
    body = event.model_dump_json()
    try:
        pipe = _redis.raw.pipeline()
        if event.kind == "browser_frame":
            pipe.set(_key(run_id, call_id, "frame"), body, ex=TTL_SECONDS)
        else:
            trace = _key(run_id, call_id, "trace")
            pipe.rpush(trace, body)
            pipe.ltrim(trace, -HISTORY_LIMIT, -1)
            pipe.expire(trace, TTL_SECONDS)
        pipe.expire(_key(run_id, call_id, "meta"), TTL_SECONDS)
        pipe.publish(_key(run_id, call_id, "events"), body)
        await pipe.execute()
    except Exception:
        logger.exception("live_browse_publish_failed")


async def send(run_id: str, call_id: str, command: BrowserCommand) -> None:
    """Queue one command for the browse to read between or during its steps."""
    if _redis is None:
        return
    queue = _key(run_id, call_id, "control")
    pipe = _redis.raw.pipeline()
    pipe.rpush(queue, command.model_dump_json())
    pipe.ltrim(queue, -COMMAND_LIMIT, -1)
    pipe.expire(queue, TTL_SECONDS)
    await pipe.execute()


def _command(raw: str | None) -> BrowserCommand | None:
    if raw is None:
        return None
    try:
        return BrowserCommand.model_validate_json(raw)
    except ValidationError:
        logger.warning("live_browse_command_unreadable")
        return None


class LiveControl:
    """One browse's command queue, as the loop reads it - `BrowserControl` over Redis."""

    def __init__(self, run_id: str, call_id: str) -> None:
        self._queue = _key(run_id, call_id, "control")

    async def poll(self) -> BrowserCommand | None:
        """The next command waiting, without waiting for one."""
        if _redis is None:
            return None
        return _command(await _redis.pop_left(self._queue))

    async def wait(self, timeout: float) -> BrowserCommand | None:
        """The next command, waiting up to `timeout` seconds for it."""
        if _redis is None:
            await anyio.sleep(timeout)
            return None
        return _command(await _redis.wait_pop_left(self._queue, timeout))


class _Access(BaseModel):
    control: bool
    own: bool
    """Whether the viewer is the person the run acts for - the only one who may keep a sign-in."""
    name: str
    user_id: str


async def access_for(meta: BrowseMeta, auth_token: str, *, recheck: bool = False) -> _Access | None:
    """What the holder of `auth_token` may do with this browse, or `None` for nothing.

    `recheck` is the re-evaluation on an already-open socket: the session token
    may have aged past its lifetime meanwhile (see `authenticate_socket_token`),
    while a revoked session or key, a removed membership or a withdrawn grant
    still refuses.

    Watching takes being the person the run acts for, editing the agent, or viewing
    runs; driving takes one of the first two, because what is done in the browser
    is done as the agent.

    An organization key is held to its own scopes rather than its issuer's role:
    it may watch with `runs:view`, never a person's own browse, and never drive -
    a browse can be signed in to its person's sites, and a read-only key driving
    one would be operating those accounts.
    """
    async with get_db_context() as db:
        try:
            caller = await authenticate_socket_key(db, auth_token)
            if caller is not None:
                key = caller.context
                if (
                    meta.personal
                    or key.organization_id != meta.organization_id
                    or not key.has(Perm.RUNS_VIEW)
                ):
                    return None
                return _Access(
                    control=False,
                    own=False,
                    name=caller.user.full_name or caller.user.email,
                    user_id=str(caller.user.id),
                )
            user = await authenticate_socket_token(db, auth_token, allow_expired=recheck)
        except AuthenticationError:
            return None
        membership = await member_repo.get(
            db, organization_id=meta.organization_id, user_id=user.id
        )
        if membership is None:
            return None
        ctx = AuthContext(
            user_id=user.id,
            organization_id=meta.organization_id,
            role=membership.role,
            is_app_admin=user.is_app_admin,
        )
        # In person: an administrator impersonating the browse's person is not
        # them, and must not keep a sign-in for them or watch their own accounts.
        own = (
            meta.user_id is not None
            and str(user.id) == meta.user_id
            and current_impersonator() is None
        )
        agent = (
            None
            if meta.agent_id is None
            else await agent_repo.get(db, meta.agent_id, organization_id=meta.organization_id)
        )
        edits = agent is not None and await resolve_access(
            db, ctx, agent, Perm.AGENTS_EDIT, resource_type=AGENT
        )
    if meta.personal and not own:
        return None
    if not (own or edits or ctx.has(Perm.RUNS_VIEW)):
        return None
    return _Access(
        control=own or edits, own=own, name=user.full_name or user.email, user_id=str(user.id)
    )


async def _load(run_id: str, call_id: str) -> tuple[BrowseMeta | None, list[str], str | None]:
    assert _redis is not None
    raw_meta = await _redis.get(_key(run_id, call_id, "meta"))
    if raw_meta is None:
        return None, [], None
    trace = await _redis.list_range(_key(run_id, call_id, "trace"))
    frame = await _redis.get(_key(run_id, call_id, "frame"))
    return BrowseMeta.model_validate_json(raw_meta), trace, frame


@contextlib.asynccontextmanager
async def _subscription(run_id: str, call_id: str) -> AsyncGenerator[PubSub]:
    assert _redis is not None
    pubsub = _redis.raw.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(_key(run_id, call_id, "events"))
    try:
        yield pubsub
    finally:
        await pubsub.aclose()


async def watch(run_id: str, call_id: str) -> AsyncGenerator[BrowserEvent]:
    """Every frame of one browse from now on, for a surface that follows it - a channel.

    Pictures are skipped: a channel posts words and a link, never a screenshot.
    Ends when Redis ends the subscription; the caller cancels it when the browse
    is over.
    """
    if _redis is None:
        return
    async with _subscription(run_id, call_id) as pubsub:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                event = BrowserEvent.model_validate_json(str(message["data"]))
            except ValidationError:
                continue
            if event.kind != "browser_frame":
                yield event


REVALIDATE_SECONDS = 30.0
"""How often an open live view asks again whether its viewer may still watch."""


async def stream(websocket: WebSocket, *, auth_token: str, run_id: str, call_id: str) -> None:
    """Serve one viewer of one browse until either side is done.

    Sends what the browse has done so far and its latest picture, then every frame
    as it happens. Reads the viewer's commands - only from a viewer who may drive
    it - and stamps each with their name, which is how the people watching see who
    has the browser, and their id, which is how the browse knows whose sign-in a
    give-back may keep.
    """
    if _redis is None:
        await websocket.close(code=1011, reason="Live view is unavailable")
        return
    meta, trace, frame = await _load(run_id, call_id)
    if meta is None:
        await websocket.close(code=_NOT_FOUND_CLOSE_CODE, reason="Browse not found")
        return
    access = await access_for(meta, auth_token)
    if access is None:
        await websocket.close(code=_FORBIDDEN_CLOSE_CODE, reason="Not allowed to watch")
        return
    await websocket.send_text(
        json.dumps(
            {
                "type": "browser_snapshot",
                "task": meta.task,
                "started_at": meta.started_at.astimezone(UTC).isoformat(),
                "can_control": access.control,
                "can_remember": access.own and meta.remembers,
                "trace": [json.loads(item) for item in trace],
                "frame": json.loads(frame) if frame else None,
            }
        )
    )

    # What the viewer may do now, not what they could at the handshake: a key
    # revoked, a membership removed or an edit grant withdrawn while the socket is
    # open ends what it may do. Asked again before every command and every
    # `REVALIDATE_SECONDS` while only frames flow.
    current = access
    lost = False

    async def still_allowed() -> bool:
        nonlocal current, lost
        fresh = await access_for(meta, auth_token, recheck=True)
        if fresh is None:
            lost = True
            return False
        current = fresh
        return True

    async def commands() -> None:
        try:
            while True:
                raw = await websocket.receive_text()
                if not await still_allowed():
                    return
                if not current.control:
                    continue
                try:
                    command = BrowserCommand.model_validate_json(raw)
                except ValidationError:
                    continue
                await send(
                    run_id,
                    call_id,
                    command.model_copy(update={"by": current.name, "by_user_id": current.user_id}),
                )
        except WebSocketDisconnect:
            return

    async with _subscription(run_id, call_id) as pubsub, anyio.create_task_group() as tasks:

        async def forward() -> None:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    await websocket.send_text(str(message["data"]))

        async def reader() -> None:
            await commands()
            tasks.cancel_scope.cancel()

        async def revalidate() -> None:
            while True:
                await anyio.sleep(REVALIDATE_SECONDS)
                if not await still_allowed():
                    break
            tasks.cancel_scope.cancel()

        tasks.start_soon(forward)
        tasks.start_soon(reader)
        tasks.start_soon(revalidate)
    if lost:
        await websocket.close(code=_FORBIDDEN_CLOSE_CODE, reason="Not allowed to watch")
