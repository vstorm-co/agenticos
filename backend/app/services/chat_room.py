"""Who has a conversation open, and the news that somebody started a turn in it.

A project's chat is several people's, at once. Each of their sockets that has the
conversation open is in its room: its presence is kept in Redis with a heartbeat,
one entry per socket, so a person with the chat open in two tabs stays here when
they close one,
and the room's channel says when the people in it change and when a turn begins -
so the others can show who is here, and follow the answer as it is written rather
than finding it on their next reload.

Redis rather than the process, for the reason `live_turn` gives: the people in one
room are on whichever API instances the load balancer gave them. Presence expires
on its own, so a socket that died without leaving drops out within `PRESENCE_TTL`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any
from uuid import UUID

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

PRESENCE_TTL = 45
"""Seconds a person counts as here after their socket last said so."""

HEARTBEAT_SECONDS = 20
"""How often an open socket says it is still here - well inside the TTL."""

PRESENCE = "presence"
TURN_BEGUN = "turn_begun"
TYPING = "typing"

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


def _here(conversation_id: str) -> str:
    return f"room:{conversation_id}:here"


def _channel(conversation_id: str) -> str:
    return f"room:{conversation_id}:events"


def _entry(user_id: UUID, socket: str) -> str:
    return f"{user_id}:{socket}"


async def join(conversation_id: str, user_id: UUID, socket: str) -> None:
    """Count this socket's person as here, and tell the room. Also the heartbeat. Never raises."""
    if _redis is None:
        return
    try:
        pipe = _redis.raw.pipeline()
        pipe.hset(_here(conversation_id), _entry(user_id, socket), str(time.time()))
        pipe.expire(_here(conversation_id), PRESENCE_TTL * 4)
        await pipe.execute()
    except Exception:
        logger.exception("chat_room_join_failed")
        return
    await _announce(conversation_id, PRESENCE)


async def leave(conversation_id: str, user_id: UUID, socket: str) -> None:
    """Stop counting this socket, and tell the room. Never raises.

    The person stays here while another of their sockets has the room open.
    """
    if _redis is None:
        return
    with contextlib.suppress(Exception):
        await _redis.raw.hdel(_here(conversation_id), _entry(user_id, socket))
    await _announce(conversation_id, PRESENCE)


async def present(conversation_id: str) -> list[UUID]:
    """The people with a socket that has the conversation open, as of the last heartbeat.

    Each once, however many of their sockets are in the room.
    """
    if _redis is None:
        return []
    try:
        seen = await _redis.hash_all(_here(conversation_id))
    except Exception:
        logger.exception("chat_room_presence_failed")
        return []
    return _people(seen)


async def present_in(conversation_ids: Sequence[str]) -> dict[str, list[UUID]]:
    """`present` for each of a page of conversations, in one round trip.

    An empty answer when Redis cannot say: the rooms are a view, and a list of
    chats is still a list without them.
    """
    if _redis is None or not conversation_ids:
        return {}
    try:
        pipe = _redis.raw.pipeline()
        for conversation_id in conversation_ids:
            pipe.hgetall(_here(conversation_id))
        rooms = await pipe.execute()
    except Exception:
        logger.exception("chat_room_presence_failed")
        return {}
    return {
        conversation_id: _people(seen)
        for conversation_id, seen in zip(conversation_ids, rooms, strict=True)
    }


def _people(seen: Mapping[str, str]) -> list[UUID]:
    cutoff = time.time() - PRESENCE_TTL
    here: list[UUID] = []
    for entry, at in seen.items():
        with contextlib.suppress(ValueError):
            person = UUID(str(entry).partition(":")[0])
            if float(at) >= cutoff and person not in here:
                here.append(person)
    return here


async def turn_begun(conversation_id: str, user_id: UUID) -> None:
    """Tell the room somebody started a turn, so the others follow it. Never raises."""
    await _announce(conversation_id, TURN_BEGUN, by=str(user_id))


async def typing(conversation_id: str, user_id: UUID) -> None:
    """Tell the room somebody is writing a message, as a messenger does. Never raises.

    Nothing is kept: the next one comes within a few seconds while they type,
    and the others stop showing it when none has.
    """
    await _announce(conversation_id, TYPING, by=str(user_id))


async def _announce(conversation_id: str, kind: str, **fields: Any) -> None:
    if _redis is None:
        return
    with contextlib.suppress(Exception):
        await _redis.raw.publish(_channel(conversation_id), json.dumps({"type": kind, **fields}))


async def events(conversation_id: str) -> AsyncGenerator[dict[str, Any]]:
    """What happens in the room from now on: people coming and going, typing, turns beginning."""
    if _redis is None:
        return
    pubsub = _redis.raw.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe(_channel(conversation_id))
    except Exception:
        # Raised, not swallowed: ending quietly read as the room having nothing
        # more to say, and the socket stopped listening for good. The listener
        # retries a failure - see `AgentSession._in_room`.
        logger.exception("chat_room_subscribe_failed")
        await pubsub.aclose()
        raise
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                event = json.loads(str(message["data"]))
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") in (PRESENCE, TURN_BEGUN, TYPING):
                yield event
    finally:
        await pubsub.aclose()
