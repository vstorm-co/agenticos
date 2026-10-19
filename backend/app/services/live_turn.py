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

LIVE_ONLY = frozenset({"browser_frame", "browser_pointer"})
"""Frames sent to whoever is following now and never kept in the trace.

A browse sends its screenshot about twelve times a second, each a full JPEG
data URL: kept, one long browse held hundreds of megabytes in the shared
Redis. Somebody arriving mid-browse is shown the next frame, a moment later -
an old one is no use to them."""

MAX_KEPT_BYTES = 256 * 1024
"""The largest frame the trace keeps. Anything bigger is still announced live,
for the same reason the frames above are: the trace is a replay of the turn's
text and steps, not an archive of what it showed."""

END = "turn_followed_to_end"
"""The frame type that closes a trace - sent to a follower as the turn being over."""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


@dataclass(frozen=True)
class Turn:
    """One running turn's handle: what its frames are kept under."""

    conversation_id: str
    token: str

    def key(self, part: str) -> str:
        return f"turn:{self.conversation_id}:{self.token}:{part}"


def _live_key(conversation_id: str) -> str:
    """The conversation's running turns, oldest first - a list, not one value.

    Two teammates can each have a turn running in one chat. One value named only
    the newest, and the newer turn ending first took it down while the older was
    still being written, which then streamed to nobody.
    """
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
        pipe = _redis.raw.pipeline()
        pipe.rpush(_live_key(conversation_id), turn.token)
        pipe.expire(_live_key(conversation_id), TTL_SECONDS)
        await pipe.execute()
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

    Only this turn leaves the conversation's running ones: another somebody
    started, before or after it, is still being written and still followed.
    """
    if _redis is None:
        return
    with contextlib.suppress(Exception):
        await _redis.raw.lrem(_live_key(turn.conversation_id), 0, turn.token)
    await _append(turn, END, {"conversation_id": turn.conversation_id}, ttl=ENDED_TTL_SECONDS)


async def _append(turn: Turn, kind: str, data: Any, *, ttl: int) -> None:
    assert _redis is not None
    try:
        # The stubs union a sync and an async return; this client is the async one.
        seq = await _redis.raw.incr(turn.key("seq"))  # ty: ignore[invalid-await]
        body = json.dumps({"seq": seq, "type": kind, "data": data}, default=str)
        trace = turn.key("trace")
        pipe = _redis.raw.pipeline()
        if kind not in LIVE_ONLY and len(body) <= MAX_KEPT_BYTES:
            pipe.rpush(trace, body)
            pipe.ltrim(trace, -HISTORY_LIMIT, -1)
            pipe.expire(trace, ttl)
        pipe.expire(turn.key("seq"), ttl)
        # The conversation's list of running turns lives as long as one of them
        # is still writing: set only at `begin`, it expired under a turn longer
        # than an hour, which nobody returning could then follow.
        if kind != END:
            pipe.expire(_live_key(turn.conversation_id), ttl)
        pipe.publish(turn.key("events"), body)
        await pipe.execute()
    except Exception:
        logger.exception("live_turn_publish_failed")


async def live_token(conversation_id: str) -> str | None:
    """The newest turn being written in the conversation now, or `None` for none."""
    if _redis is None:
        return None
    try:
        running = await _redis.list_range(_live_key(conversation_id))
    except Exception:
        # Following is a view, as everything else here: Redis being away must
        # not close the chat socket that asked - it reads as nothing running.
        logger.exception("live_turn_is_live_failed")
        return None
    return running[-1] if running else None


async def follow(conversation_id: str, token: str) -> AsyncGenerator[dict[str, Any]]:
    """Every frame of one turn: what it has sent, then what it sends.

    Ends after the frame that closes the turn. Each frame is `{"seq", "type",
    "data"}`, as the turn's socket sent it. Ends early, without that frame, when
    Redis goes away: following is a view, and the follower then says the turn is
    over rather than leave the reader's chat waiting on it.
    """
    if _redis is None:
        return
    turn = Turn(conversation_id, token)
    pubsub = _redis.raw.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe(turn.key("events"))
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
    except Exception:
        logger.exception("live_turn_follow_failed")
    finally:
        with contextlib.suppress(Exception):
            await pubsub.aclose()


def _frame(raw: str) -> dict[str, Any] | None:
    try:
        frame = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(frame, dict) or not isinstance(frame.get("seq"), int):
        return None
    return frame
