"""A chat turn that is still being written, for a person who comes back to it.

A turn outlives the socket it was asked on: the person opens another chat, the
tab is closed, the page is reloaded, and the agent finishes and saves the answer
anyway (`AgentSession.shutdown`). What they could not do was *watch* it again -
coming back showed the question and a note to check later, while the agent was
still reading files and running commands a click away.

So every frame of a running turn is also kept here, in Redis: appended to the
turn's trace and announced on its channel, each with a sequence number. Keyed by
the turn as well as the conversation, because two tabs can each start a turn in
one conversation, and sharing keys let the second wipe the first one's trace and
the first to finish end the other's for everybody following. The conversation's
`live` marker names the turn a follower should be shown - the latest - and a turn
ending takes the marker down only while it is still that turn's. A socket that asks to follow the conversation is sent the trace
and then the channel, and the sequence numbers are what make the seam exact - it
subscribes first, reads the trace, and forwards only what comes after the last
frame the trace held, so a frame published between the two is neither lost nor
shown twice.

Redis rather than the process the turn runs in, because the person's new socket
lands on whichever API instance the load balancer picks. Frames that ask the
person for something - a question, a connection - are not kept: the session they
belong to is the one waiting, and an answer from another socket cannot reach it.
A turn's trace expires shortly after it ends, and an hour after its last frame
whatever happened; the transcript is the record, this is a view.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

TTL_SECONDS = 3600
"""How long a turn's trace outlives its last frame, if nothing ends it first."""

ENDED_TTL_SECONDS = 120
"""How long a finished turn's trace is kept, for a follower already reading it."""

HISTORY_LIMIT = 20_000
"""Frames kept per turn. A long answer is thousands of text deltas; past this the oldest go."""

NOT_KEPT = frozenset(
    {"ask_user", "connect_account", "user_prompt", "conversation_created", "steer_unapplied"}
)
"""Frames meant for the socket that sent the message, not for someone watching.

A question or a connection request waits on the session that asked it, which an
answer from another socket cannot reach; the prompt is already in the transcript;
`conversation_created` names a chat the follower already has open."""

END = "turn_followed_to_end"
"""The frame type that closes a trace - sent to a follower as the turn being over."""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


_END_IF_OURS = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""
"""Take the conversation's marker down only if it still names this turn - atomically,
so a turn begun between the check and the delete keeps its own."""


@dataclass(frozen=True)
class Turn:
    """One running turn's handle: what its frames are kept under."""

    conversation_id: str
    token: str

    def key(self, part: str) -> str:
        return f"turn:{self.conversation_id}:{self.token}:{part}"


def _live_key(conversation_id: str) -> str:
    return f"turn:{conversation_id}:live"


async def begin(conversation_id: str) -> Turn | None:
    """Start a trace for the conversation's new turn, and point followers at it.

    `None` without Redis, or when it refused: the turn runs either way, unwatched.
    Never raises.
    """
    if _redis is None:
        return None
    turn = Turn(conversation_id, uuid.uuid4().hex)
    try:
        await _redis.raw.set(_live_key(conversation_id), turn.token, ex=TTL_SECONDS)
    except Exception:
        logger.exception("live_turn_begin_failed")
        return None
    return turn


async def publish(turn: Turn, kind: str, data: Any) -> None:
    """Keep and announce one frame of the running turn. Never raises."""
    if _redis is None or kind in NOT_KEPT:
        return
    await _append(turn, kind, data, ttl=TTL_SECONDS)


async def end(turn: Turn) -> None:
    """Close the turn's trace: its followers stop, and it expires soon after. Never raises.

    The conversation stops reading as live only if this was still its latest
    turn; a newer one somebody started meanwhile is still being written.
    """
    if _redis is None:
        return
    with contextlib.suppress(Exception):
        await _redis.raw.eval(_END_IF_OURS, 1, _live_key(turn.conversation_id), turn.token)
    await _append(turn, END, {"conversation_id": turn.conversation_id}, ttl=ENDED_TTL_SECONDS)


async def _append(turn: Turn, kind: str, data: Any, *, ttl: int) -> None:
    assert _redis is not None
    try:
        # The stubs union a sync and an async return; this client is the async one.
        seq = await _redis.raw.incr(turn.key("seq"))  # ty: ignore[invalid-await]
        body = json.dumps({"seq": seq, "type": kind, "data": data}, default=str)
        trace = turn.key("trace")
        pipe = _redis.raw.pipeline()
        pipe.rpush(trace, body)
        pipe.ltrim(trace, -HISTORY_LIMIT, -1)
        pipe.expire(trace, ttl)
        pipe.expire(turn.key("seq"), ttl)
        pipe.publish(turn.key("events"), body)
        await pipe.execute()
    except Exception:
        logger.exception("live_turn_publish_failed")


async def is_live(conversation_id: str) -> bool:
    """Whether a turn is being written in the conversation now."""
    if _redis is None:
        return False
    return await _redis.raw.exists(_live_key(conversation_id)) > 0


async def follow(conversation_id: str) -> AsyncGenerator[dict[str, Any]]:
    """Every frame of the conversation's latest turn: what it has sent, then what it sends.

    Ends after the frame that closes the turn, and at once when no turn is running.
    Each frame is `{"seq", "type", "data"}`, as the turn's socket sent it.
    """
    if _redis is None:
        return
    token = await _redis.raw.get(_live_key(conversation_id))
    if token is None:
        return
    # A string: the client decodes responses.
    turn = Turn(conversation_id, str(token))
    pubsub = _redis.raw.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(turn.key("events"))
    try:
        last = 0
        for raw in await _redis.list_range(turn.key("trace")):
            frame = _frame(raw)
            if frame is None:
                continue
            last = frame["seq"]
            yield frame
            if frame["type"] == END:
                return
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            frame = _frame(str(message["data"]))
            if frame is None or frame["seq"] <= last:
                continue
            last = frame["seq"]
            yield frame
            if frame["type"] == END:
                return
    finally:
        await pubsub.aclose()


def _frame(raw: str) -> dict[str, Any] | None:
    try:
        frame = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(frame, dict) or not isinstance(frame.get("seq"), int):
        return None
    return frame
