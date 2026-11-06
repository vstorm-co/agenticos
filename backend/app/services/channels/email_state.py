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
  made. The durable delivery job also retains the signed body, so a worker can rebuild
  this short-lived cache after a restart or a queue delay.
"""

import json
from collections.abc import AsyncGenerator, Generator, Iterable
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass

from app.clients.redis import RedisClient

THREAD_TTL_SECONDS = 30 * 24 * 60 * 60
ATTACHMENT_TTL_SECONDS = 15 * 60
MAX_CACHED_ATTACHMENT_BYTES = 64 * 1024 * 1024
MAX_CACHED_ATTACHMENTS = 1024
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


_reply_thread: ContextVar[tuple[str, str, Thread] | None] = ContextVar(
    "email_reply_thread", default=None
)


@contextmanager
def replying_to(bot_address: str, chat_id: str, thread: Thread) -> Generator[None]:
    """Pin replies and prompts to this delivery, including tasks spawned while handling it."""
    token = _reply_thread.set((bot_address, chat_id, thread))
    try:
        yield
    finally:
        _reply_thread.reset(token)


async def stash_attachments(bot_id: str, values: dict[str, str]) -> bool:
    """Atomically admit and store one delivery; no reservation survives a failed stash."""
    if not values:
        return True
    if _redis is None:
        return False
    return await _redis.cache_bounded_values(
        f"channel:email:attachments:{bot_id}",
        values=values,
        capacity=MAX_CACHED_ATTACHMENT_BYTES,
        ttl=ATTACHMENT_TTL_SECONDS,
        max_items=MAX_CACHED_ATTACHMENTS,
    )


async def discard_attachments(handles: Iterable[str]) -> None:
    for handle in handles:
        await take_attachment(handle)


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
    pinned = _reply_thread.get()
    if pinned is not None and pinned[:2] == (bot_address, chat_id):
        return pinned[2]
    if _redis is None:
        return None
    stored = await _redis.get(_thread_key(bot_address, chat_id))
    return Thread(**json.loads(stored)) if stored else None


async def take_attachment(handle: str) -> str | None:
    """Consume a file and its capacity together, or return None after expiry."""
    if _redis is None:
        return None
    bot_id = handle.split(":", 1)[0]
    value = await _redis.take_bounded_value(
        f"channel:email:attachments:{bot_id}", handle, ttl=ATTACHMENT_TTL_SECONDS
    )
    # Drain files queued before the bounded-cache upgrade (at most fifteen minutes).
    return value if value is not None else await _redis.getdel(f"channel:email:file:{handle}")


@asynccontextmanager
async def in_worker() -> AsyncGenerator[None]:
    """Own the channel stores for the lifetime of a worker, including numbered replies."""
    from app.services.channels import dedupe, sms_prompts

    client = RedisClient()
    await client.connect()
    configure(client)
    sms_prompts.configure(client)
    dedupe.configure(client)
    try:
        yield
    finally:
        configure(None)
        sms_prompts.configure(None)
        dedupe.configure(None)
        await client.close()
