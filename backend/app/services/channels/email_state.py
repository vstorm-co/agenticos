"""What an e-mail channel remembers between a message and its reply (#2082).

Held in the deployment's shared Redis because the reply may be written by a different
worker than the one that received the message.

- **The thread.** Keyed by the bot's address and the sender's: subject and message ids of
  the last message from that sender, so the reply
  carries `Re: subject`, `In-Reply-To` and `References` and a mail client files it under
  the conversation it answers. Kept for `THREAD_TTL_SECONDS`; after that a reply starts a
  fresh thread, which is only cosmetic.
- **Attachments.** The relay sends files inline; the router fetches them later, in the
  background, through the adapter. They wait here, briefly, under a handle the adapter
  made - not on disk and not in the database, because nothing about a file somebody mailed
  needs to outlive the turn that reads it.
"""

import json
from dataclasses import asdict, dataclass

from app.clients.redis import RedisClient

THREAD_TTL_SECONDS = 30 * 24 * 60 * 60
ATTACHMENT_TTL_SECONDS = 15 * 60
SEEN_TTL_SECONDS = 24 * 60 * 60
MAX_REFERENCES = 20
"""Headers grow with every reply; a mail server refuses a long enough `References`."""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


@dataclass(frozen=True)
class Thread:
    subject: str
    message_id: str | None
    references: list[str]


def _thread_key(bot_address: str, chat_id: str) -> str:
    return f"channel:email:thread:{bot_address}:{chat_id}"


async def remember_thread(
    bot_address: str,
    chat_id: str,
    *,
    subject: str,
    message_id: str | None,
    references: list[str],
) -> None:
    """Keep the thread the next reply to this sender belongs to."""
    if _redis is None:
        return
    chain = [*references, *([message_id] if message_id else [])][-MAX_REFERENCES:]
    thread = Thread(subject=subject, message_id=message_id, references=chain)
    await _redis.set(
        _thread_key(bot_address, chat_id), json.dumps(asdict(thread)), ttl=THREAD_TTL_SECONDS
    )


async def thread_of(bot_address: str, chat_id: str) -> Thread | None:
    """The thread to answer into, or `None` when there is none to continue."""
    if _redis is None:
        return None
    stored = await _redis.get(_thread_key(bot_address, chat_id))
    return Thread(**json.loads(stored)) if stored else None


async def stash_attachment(handle: str, content_base64: str) -> None:
    """Hold one inbound file until the router has read it."""
    if _redis is not None:
        await _redis.set(f"channel:email:file:{handle}", content_base64, ttl=ATTACHMENT_TTL_SECONDS)


async def take_attachment(handle: str) -> str | None:
    """The base64 content of a stashed file, or `None` once it has expired."""
    if _redis is None:
        return None
    return await _redis.get(f"channel:email:file:{handle}")


async def first_delivery(bot_id: str, message_id: str | None) -> bool:
    """Whether this is the first time this message id reached this bot.

    A relay retries when it hears nothing back, and a mail server can deliver the same
    message twice; either would run the agent twice on one mail. Without Redis, or without
    a message id, there is nothing to compare and the message goes through.
    """
    if _redis is None or not message_id:
        return True
    return await _redis.set(
        f"channel:email:seen:{bot_id}:{message_id}", "1", ttl=SEEN_TTL_SECONDS, nx=True
    )
