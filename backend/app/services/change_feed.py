"""Live change events: what an open console page hears when something changes elsewhere (#2061).

A write through the public API - a key in Postman, Claude Code over the platform's
MCP server, the in-app Platform assistant, another person's console - commits, and
a page already showing the old rows has no way to know. This module closes that:

- :class:`ChangeFeedMiddleware` watches every write that succeeded - a public
  route or one only the console calls, like sharing, routines or channel bots
  (#2099) - and publishes one :class:`ChangeEvent` to its organization's Redis
  channel. It sits at the HTTP boundary rather than in each service so that no
  write path can forget it, and it publishes once the response has gone out -
  which is after the commit, because `DBSession` commits before the response is
  written - so a page that refetches on the event reads the new row.
- :func:`publish_run` is the one change no request makes: a run moving through
  its states. The runner calls it after each of its own commits, in the API
  process or in the worker that fired a routine.
- :func:`stream_changes` serves one console tab's socket. It forwards an event only
  when the subscriber may see the resource it is about, and re-reads their access
  for every event, so a socket outliving a membership or a revoked key goes quiet.

Live updates are a convenience over a page that already works without them: a
publish that fails is logged and dropped, and a disconnected tab behaves as the
console always did.
"""

import contextlib
import json
import logging
import re
import zlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import anyio
from fastapi import WebSocket
from redis.asyncio.client import PubSub
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.permissions import AuthContext, Perm
from app.core.permissions import Scope as PermScope
from app.db.models.agent_run import AgentRun
from app.db.session import get_db_context
from app.repositories import agent as agent_repo
from app.repositories import artifact as artifact_repo
from app.repositories import context as context_repo
from app.repositories import knowledge_base as knowledge_base_repo
from app.repositories import mcp_connection as mcp_connection_repo
from app.repositories import member as member_repo
from app.repositories import organization_secret as secret_repo
from app.repositories import skill as skill_repo
from app.schemas.change_event import ChangeAction, ChangeEvent, ChangeResource, ChangeSurface
from app.services.access import (
    AGENT,
    ARTIFACT,
    COLLECTION,
    CONTEXT,
    MCP_CONNECTION,
    SECRET,
    SKILL,
    OwnedResource,
    ResourceType,
    resolve_access,
)
from app.services.ws_auth import authenticate_socket_key, authenticate_socket_token

logger = logging.getLogger(__name__)

_REVOKED_CLOSE_CODE = 4403
"""Not retried by the console (`use-websocket.ts`): access that is gone does not
come back by reconnecting."""

CONSOLE_TAB_HEADER = "x-console-tab"
_TAB = re.compile(r"[A-Za-z0-9-]{1,64}")
"""What a tab id may look like - it is echoed to every subscriber, so nothing else."""


def console_tab(value: str | None) -> str | None:
    """The tab id a request carried, or `None` when it carried none worth echoing."""
    return value if value is not None and _TAB.fullmatch(value) else None


_WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BODY_LIMIT = 256 * 1024
"""How much of a response is kept whole to read a created row's `id` from. A
longer one keeps only its start (`_HEAD_KEPT`), which still names the row."""
_HEAD_KEPT = 4096
"""What of a longer answer is kept: enough for the id it opens with."""


@dataclass(frozen=True)
class ChangeOrigin:
    """Who made a request, as the change it makes will be attributed.

    Put on `request.state` by the dependencies that build the caller's context,
    which is the one place that knows both the member and the credential.
    """

    organization_id: UUID
    actor_user_id: UUID
    actor_name: str
    surface: ChangeSurface
    tab: str | None = None
    """The console tab the request came from (`X-Console-Tab`), opaque."""


@dataclass(frozen=True)
class _Feed:
    prefix: str
    resource: ChangeResource | None
    id_param: str | None = None
    """The path parameter naming the row. A write under the prefix that does not
    carry it created one, and the row's id is read from the response."""
    creates: bool = True
    """Whether a write naming no row made one. A per-person list - the inbox, its
    preferences - is changed in bulk and its writes never answer with a row."""


def _shared(prefix: str, resource: ChangeResource) -> _Feed:
    """A resource's sharing routes: a change to who can see that row."""
    return _Feed(f"{prefix}/{{resource_id}}/sharing", resource, "resource_id")


# First match wins, so a route that is not a change - or is a change to something
# else - sits above the prefix that would otherwise claim it.
_FEEDS = (
    _Feed("/agents/{agent_id}/run", None),
    _Feed("/agents/{agent_id}/validate", None),
    _Feed("/agents/{agent_id}/clone", "agent"),
    # Firing a routine by hand is a run, which publishes its own events.
    _Feed("/agents/{agent_id}/triggers/{trigger_id}/run", None),
    _Feed("/agents/{agent_id}/triggers", "trigger", "agent_id"),
    # An embed is its own row with its own page, not a change to an agent.
    _Feed("/agents/embeds", None),
    _shared("/agents", "agent"),
    _Feed("/agents", "agent", "agent_id"),
    _Feed("/apps/{artifact_id}/follow", None),
    _shared("/apps", "artifact"),
    _Feed("/apps", "artifact", "artifact_id"),
    # The deprecated paths from before apps were called that (#2071).
    _Feed("/artifacts/{artifact_id}/follow", None),
    _shared("/artifacts", "artifact"),
    _Feed("/artifacts", "artifact", "artifact_id"),
    _shared("/context", "context"),
    _Feed("/context", "context", "context_id"),
    _shared("/kb", "knowledge_base"),
    _Feed("/kb", "knowledge_base", "kb_id"),
    _shared("/skills", "skill"),
    _Feed("/skills", "skill", "skill_id"),
    _shared("/secrets", "secret"),
    _Feed("/secrets", "secret", "secret_id"),
    # Starting an OAuth dance or probing a server changes no row.
    _Feed("/mcp-connections/oauth", None),
    _Feed("/mcp-connections/{connection_id}/test", None),
    _shared("/mcp-connections", "mcp_connection"),
    _Feed("/mcp-connections", "mcp_connection", "connection_id"),
    _Feed("/channels/bots", "channel", "bot_id"),
    _Feed("/notifications", "notification", "notification_id", creates=False),
    _Feed("/orgs/{org_id}/members", "member", "target_user_id"),
    _Feed("/orgs/{org_id}/invitations", "invitation", "invitation_id"),
    _Feed("/orgs/{org_id}/groups", "group", "group_id"),
    _Feed("/orgs/{org_id}", "organization", "org_id"),
    # The assistant is the organization's own setting, heard by everyone in it.
    _Feed("/assistant", "organization", creates=False),
)

_OWNED: dict[ChangeResource, ResourceType] = {
    "agent": AGENT,
    "trigger": AGENT,
    "skill": SKILL,
    "context": CONTEXT,
    "knowledge_base": COLLECTION,
    "artifact": ARTIFACT,
    "secret": SECRET,
    "mcp_connection": MCP_CONNECTION,
}

_redis: RedisClient | None = None


async def connect_in_worker() -> None:
    """Give a worker process a Redis to publish on, once.

    A routine's run executes in the worker, a process that ran none of the API's
    startup, so the lifespan's `configure` never reaches it and every event it
    published went nowhere - the run an open Activity page most wants to see
    arrive. `python -m app.worker` calls this on start; the client lives for the
    process.
    """
    global _redis
    if _redis is not None:
        return
    client = RedisClient()
    await client.connect()
    _redis = client


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the lifespan beside the other modules that reach Redis from outside
    a request's dependencies: the middleware runs above them, and a socket lives
    far longer than the request that opened it.
    """
    global _redis
    _redis = redis


def _channel(organization_id: UUID) -> str:
    return f"changes:{organization_id}"


def _template(path: str, path_params: dict[str, Any]) -> str:
    """The route's path with each parameter's value put back as its name.

    A nested router's route object knows only its own part of the path, so the
    full template is rebuilt from the path that was requested.
    """
    names = {str(value): name for name, value in path_params.items()}
    return "/".join(
        f"{{{names[segment]}}}" if segment in names else segment for segment in path.split("/")
    )


def _feed(template: str) -> _Feed | None:
    for feed in _FEEDS:
        if template == feed.prefix or template.startswith(feed.prefix + "/"):
            return feed
    return None


_LEADING_ID = re.compile(
    rb'^\s*\{\s*"id"\s*:\s*"'
    rb"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
"""An object whose first key is its id - every row's read schema - as far as it was kept."""


def _created_id(body: bytes) -> UUID | None:
    with contextlib.suppress(ValueError):
        payload = json.loads(body)
        if isinstance(payload, dict):
            return UUID(str(payload.get("id")))
    # Longer than was kept: the start of it still names the row.
    leading = _LEADING_ID.match(body)
    return UUID(leading.group(1).decode()) if leading else None


def _decoded(body: bytes, encoding: str) -> bytes:
    """The answer as the route wrote it. GZip sits inside this middleware, so a
    long create answer arrives compressed; it is inflated no further than a row
    could be long, and an answer that will not inflate is read as naming no row."""
    if encoding != "gzip":
        return body
    try:
        return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(body, _BODY_LIMIT)
    except zlib.error:
        return b""


def change_for(
    *,
    method: str,
    path: str,
    path_params: dict[str, Any],
    origin: ChangeOrigin,
    body: bytes,
) -> ChangeEvent | None:
    """The change a successful write made, or `None` when it made none."""
    template = _template(path.removeprefix(settings.API_V1_STR), path_params)
    feed = _feed(template)
    if feed is None or feed.resource is None:
        return None
    named = path_params.get(feed.id_param) if feed.id_param else None
    action: ChangeAction
    if named is not None:
        row_id: UUID | None = UUID(str(named))
        ends_on_row = template.endswith(f"{{{feed.id_param}}}")
        action = "deleted" if method == "DELETE" and ends_on_row else "updated"
    elif feed.creates:
        row_id = _created_id(body)
        action = "created"
    else:
        row_id = None
        action = "updated"
    return ChangeEvent(
        organization_id=origin.organization_id,
        resource=feed.resource,
        id=row_id,
        action=action,
        surface=origin.surface,
        actor_user_id=origin.actor_user_id,
        actor_name=origin.actor_name,
        origin_tab=origin.tab,
    )


def run_event(run: AgentRun, action: ChangeAction) -> ChangeEvent:
    """The event a run's state change publishes, built from the row while it is
    still attached - publishing may happen after its session has moved on."""
    return ChangeEvent(
        organization_id=run.organization_id,
        resource="run",
        id=run.id,
        action=action,
        surface="run",
        actor_user_id=run.user_id,
        actor_name=None,
    )


async def publish_run(run: AgentRun, action: ChangeAction) -> None:
    """Tell open consoles a run started, parked or finished. Called after the
    commit that made the state readable, so a page that refetches sees it.

    Nothing is built where nothing listens - a process with no Redis, like the
    CLI - because this sits on every run's path."""
    if _redis is None:
        return
    await publish(run_event(run, action))


async def publish(event: ChangeEvent) -> None:
    """Tell the organization's open consoles. Never raises: the write it reports
    has already succeeded, and a page that misses it is no worse off than before."""
    if _redis is None:
        return
    try:
        await _redis.raw.publish(_channel(event.organization_id), event.model_dump_json())
    except Exception:
        logger.exception("change_feed_publish_failed", extra={"resource": event.resource})


class ChangeFeedMiddleware:
    """Publishes the change each successful write made.

    Pure ASGI, so a response passes through unchanged and nothing is re-streamed.
    The event is published after the app returns, when the response has been sent.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _WRITES:
            await self.app(scope, receive, send)
            return
        status = 0
        encoding = ""
        body = bytearray()
        truncated = False

        async def watch(message: Message) -> None:
            nonlocal status, encoding, truncated
            if message["type"] == "http.response.start":
                status = message["status"]
                encoding = Headers(raw=message["headers"]).get("content-encoding", "")
            elif not truncated:
                body.extend(message.get("body", b""))
                if len(body) > _BODY_LIMIT:
                    # The start is kept, not the whole: a long answer still opens
                    # with the id of the row it made.
                    del body[_HEAD_KEPT:]
                    truncated = True
            await send(message)

        await self.app(scope, receive, watch)
        origin = scope.get("state", {}).get("change_origin")
        if not 200 <= status < 300 or not isinstance(origin, ChangeOrigin):
            return
        event = change_for(
            method=scope["method"],
            path=scope["path"],
            path_params=scope.get("path_params", {}),
            origin=origin,
            body=_decoded(bytes(body), encoding),
        )
        if event is not None:
            await publish(event)


async def _row(db: AsyncSession, event: ChangeEvent, row_id: UUID) -> OwnedResource | None:
    organization_id = event.organization_id
    if event.resource in ("agent", "trigger"):
        return await agent_repo.get(db, row_id, organization_id=organization_id)
    if event.resource == "secret":
        return await secret_repo.get(db, row_id, organization_id=organization_id)
    if event.resource == "mcp_connection":
        return await mcp_connection_repo.get_org_scoped_by_id(
            db, connection_id=row_id, organization_id=organization_id
        )
    if event.resource == "skill":
        return await skill_repo.get(db, row_id, organization_id=organization_id)
    if event.resource == "context":
        return await context_repo.get(db, row_id, organization_id=organization_id)
    if event.resource == "artifact":
        return await artifact_repo.get(db, row_id, organization_id=organization_id)
    return await knowledge_base_repo.get_by_id(db, row_id)


def as_heard(ctx: AuthContext, event: ChangeEvent) -> ChangeEvent:
    """The frame as this subscriber may read it: who made the change is the member
    directory, so a key without `members:view` hears the change without its actor."""
    if ctx.has(Perm.MEMBERS_VIEW):
        return event
    return event.model_copy(update={"actor_user_id": None, "actor_name": None})


async def visible(db: AsyncSession, ctx: AuthContext, event: ChangeEvent) -> bool:
    """Whether the subscriber `ctx` may hear about this change.

    Exactly what they could read: a row they may view, or for members, groups and
    the organization itself, being in it. A deleted row cannot be read back, so its
    deletion reaches only those whose role already reaches every row of its kind -
    anyone else learning it would learn that a row they could not see existed.

    Runs and channel bots are read through a permission rather than per row - the
    run history and the bot list are each one gate - and an inbox is its owner's
    alone, whoever else is in the organization.
    """
    if event.organization_id != ctx.organization_id:
        return False
    if event.resource == "invitation":
        return ctx.has(Perm.MEMBERS_MANAGE)
    if event.resource in ("member", "group"):
        # Who joined, left or moved department is the member directory.
        return ctx.has(Perm.MEMBERS_VIEW)
    if event.resource == "channel":
        return ctx.has(Perm.CHANNELS_MANAGE)
    if event.resource == "notification":
        return event.actor_user_id == ctx.user_id
    if event.resource == "run":
        # The approvals inbox lists parked runs to whoever decides them.
        return ctx.has(Perm.RUNS_VIEW) or ctx.has(Perm.APPROVALS_DECIDE)
    resource_type = _OWNED.get(event.resource)
    if resource_type is None:
        return True
    if ctx.scope_for(resource_type.view) is PermScope.ALL:
        return True
    if event.action == "deleted":
        # The row is gone, so who could read it cannot be asked. The person who
        # deleted it could, and their other tabs still show it.
        return event.actor_user_id is not None and event.actor_user_id == ctx.user_id
    if event.id is None:
        return False
    row = await _row(db, event, event.id)
    return row is not None and await resolve_access(
        db, ctx, row, resource_type.view, resource_type=resource_type
    )


async def _subscriber(
    db: AsyncSession, auth_token: str, organization_id: UUID
) -> AuthContext | None:
    """The socket holder's access now, or `None` when they no longer have any."""
    try:
        caller = await authenticate_socket_key(db, auth_token)
        if caller is not None:
            return caller.context
        user = await authenticate_socket_token(db, auth_token, allow_expired=True)
    except AuthenticationError:
        return None
    membership = await member_repo.get(db, organization_id=organization_id, user_id=user.id)
    if membership is None:
        return None
    return AuthContext(
        user_id=user.id,
        organization_id=organization_id,
        role=membership.role,
        is_app_admin=user.is_app_admin,
    )


@contextlib.asynccontextmanager
async def _subscription(redis: RedisClient, organization_id: UUID) -> AsyncGenerator[PubSub]:
    pubsub = redis.raw.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(_channel(organization_id))
    try:
        yield pubsub
    finally:
        await pubsub.aclose()


async def _events(pubsub: PubSub) -> AsyncGenerator[ChangeEvent]:
    async for message in pubsub.listen():
        if message["type"] == "message":
            yield ChangeEvent.model_validate_json(message["data"])


async def _until_disconnect(websocket: WebSocket, cancel: anyio.CancelScope) -> None:
    # The client never sends anything; a frame it does send is read and dropped.
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass
    cancel.cancel()


async def stream_changes(websocket: WebSocket, *, organization_id: UUID, auth_token: str) -> None:
    """Forward the organization's changes to an accepted socket until it closes.

    Closes with 4403 the first time the holder's access is found gone - a revoked
    session or key, or a membership that ended - and with 1011 when this process
    has no Redis to listen on or Redis ends the subscription.
    """
    if _redis is None:
        await websocket.close(code=1011, reason="Live updates are unavailable")
        return
    async with (
        _subscription(_redis, organization_id) as pubsub,
        contextlib.aclosing(_events(pubsub)) as events,
        anyio.create_task_group() as tasks,
    ):
        tasks.start_soon(_until_disconnect, websocket, tasks.cancel_scope)
        async for event in events:
            # Shielded from the disconnect (#2241): cancelled mid-query, asyncpg's
            # connection was cancelled while it closed too, and the pool handed
            # the dead connection to the next request on this worker, a 500. The
            # session finishes and goes back whole; the socket is written only
            # outside the shield, and only while the client is still there.
            with anyio.CancelScope(shield=True):
                async with get_db_context() as db:
                    ctx = await _subscriber(db, auth_token, organization_id)
                    heard = (
                        as_heard(ctx, event).model_dump_json()
                        if ctx is not None and await visible(db, ctx, event)
                        else None
                    )
            if tasks.cancel_scope.cancel_called:
                return
            if ctx is None:
                await websocket.close(code=_REVOKED_CLOSE_CODE, reason="Access revoked")
                tasks.cancel_scope.cancel()
                return
            if heard is not None:
                await websocket.send_text(heard)
        # Redis ended the subscription. 1011 is one the console retries, and a
        # reconnect subscribes again.
        await websocket.close(code=1011, reason="Live updates were interrupted")
        tasks.cancel_scope.cancel()
