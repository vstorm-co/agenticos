"""WhatsApp, over Meta's Cloud API (#2076).

A bot is a WhatsApp Business number. Meta posts every message to
`/api/v1/whatsapp/{bot_id}/webhook`; the route checks the HMAC over the raw body
(`whatsapp_payload`) before a field is read, and this adapter answers through the
Graph client. Nothing is polled and no connection is held.

**What a customer is.** A business-scoped user id (BSUID), never a phone number:
it is the chat id answers go to, and `WhatsAppCredentials` - the bot's "token" in
the channel layer - carries the number the answer is sent from.

**Replies cannot be edited.** WhatsApp has no edit, so `begin_reply` answers
`None` and the router sends one finished message. What the customer sees while the
agent works is the read receipt and the typing indicator, which Meta shows for 25
seconds and which is re-sent until the answer goes out.
"""

import asyncio
import logging
from typing import Any

from app.core.background import spawn
from app.services.channels import connection_state
from app.services.channels.base import ChannelAdapter, IncomingMessage, OutgoingMessage
from app.services.channels.whatsapp_format import split_message, to_whatsapp
from app.services.channels.whatsapp_graph import (
    TOKEN_REFUSED,
    WhatsAppCredentials,
    WhatsAppGraph,
    WhatsAppGraphError,
    WhatsAppTokenRefused,
)
from app.services.channels.whatsapp_payload import verify_signature

logger = logging.getLogger(__name__)

TYPING_REFRESH_SECONDS: float = 20
"""Meta clears the indicator after 25 seconds; this re-sends it before that."""

TYPING_MAX_SECONDS: float = 300
"""A turn that has not answered by now is not going to; stop claiming it is typing."""

_sleep = asyncio.sleep
"""The refresher's clock, a name of its own so a test can advance it by hand."""

FILES_NOT_YET = "(A chart or file came with this answer; WhatsApp can't show it here yet.)"
"""Said instead of dropping a file silently, until the adapter can send files."""


def _typing_failed(creds: WhatsAppCredentials | None, failure: Exception) -> None:
    """Log that the indicator failed: which bot and Graph's code, never the cause."""
    code = (
        (failure.details or {}).get("code")
        if isinstance(failure, WhatsAppGraphError | WhatsAppTokenRefused)
        else None
    )
    logger.warning(
        "whatsapp_typing_failed",
        extra={"bot_id": creds.bot_id if creds else None, "code": code},
    )


class WhatsAppAdapter(ChannelAdapter):
    platform = "whatsapp"

    def __init__(self, graph: WhatsAppGraph | None = None) -> None:
        self._graph = graph or WhatsAppGraph()
        self._typing: dict[tuple[str, str], asyncio.Task[Any]] = {}

    async def aclose(self) -> None:
        for key in list(self._typing):
            self._stop_typing(key)
        await self._graph.aclose()

    def _stop_typing(self, key: tuple[str, str]) -> None:
        task = self._typing.pop(key, None)
        if task is not None:
            task.cancel()

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send the answer as WhatsApp text, in as many messages as its limit needs.

        Raises:
            WhatsAppTokenRefused: Meta refused the access token; the bot is marked
                down in the console list until a send succeeds.
            WhatsAppGraphError: Any other refusal.
        """
        creds = WhatsAppCredentials.decode(bot_token)
        self._stop_typing((creds.bot_id, msg.platform_chat_id))
        text = to_whatsapp(msg.text).strip()
        if msg.image_png is not None or msg.attachments:
            text = f"{text}\n\n{FILES_NOT_YET}" if text else FILES_NOT_YET
        try:
            for index, chunk in enumerate(split_message(text)):
                await self._graph.send_text(
                    creds,
                    recipient=msg.platform_chat_id,
                    body=chunk,
                    reply_to=msg.reply_to_message_id if index == 0 else None,
                )
        except WhatsAppTokenRefused:
            await connection_state.record_down(creds.bot_id, TOKEN_REFUSED)
            raise
        # Read from the shared entry, not remembered here: the worker whose send
        # succeeds is rarely the one that saw the refusal.
        recorded = await connection_state.read(creds.bot_id)
        if recorded is not None and recorded.state == "down":
            await connection_state.record_up(creds.bot_id)

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Mark the customer's message read and show "typing" until the answer is sent.

        Always `None`: WhatsApp cannot edit a message, so the router sends the
        answer whole - and `open_answer`'s `None` keeps a streaming bot off the
        edit path too. Never fatal; the indicator is decoration.
        """
        if not msg.reply_to_message_id:
            return None
        creds: WhatsAppCredentials | None = None
        try:
            creds = WhatsAppCredentials.decode(bot_token)
            await self._graph.mark_read(creds, message_id=msg.reply_to_message_id, typing=True)
        except Exception as failure:
            _typing_failed(creds, failure)
            return None
        key = (creds.bot_id, msg.platform_chat_id)
        self._stop_typing(key)
        self._typing[key] = spawn(
            self._keep_typing(key, creds, msg.reply_to_message_id),
            name=f"whatsapp_typing:{creds.bot_id}",
        )
        return None

    async def _keep_typing(
        self, key: tuple[str, str], creds: WhatsAppCredentials, message_id: str
    ) -> None:
        try:
            waited = 0.0
            while waited + TYPING_REFRESH_SECONDS <= TYPING_MAX_SECONDS:
                await _sleep(TYPING_REFRESH_SECONDS)
                waited += TYPING_REFRESH_SECONDS
                await self._graph.mark_read(creds, message_id=message_id, typing=True)
        except Exception as failure:
            _typing_failed(creds, failure)
        # Not in a `finally`: a cancelled refresher was already taken out of the
        # table by whoever cancelled it, and a newer reply may own the key by now.
        self._typing.pop(key, None)

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """WhatsApp has nothing to poll: Meta posts every message to the bot's endpoint."""

    async def stop_polling(self, bot_id: str) -> None:
        """Nothing was started."""

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """The callback is set in Meta's app dashboard, not through an API.

        Logged so an operator has the address to paste.
        """
        logger.info("WhatsApp: set the app's webhook callback URL to %s", url)
        return False

    async def delete_webhook(self, bot_token: str) -> bool:
        return False

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Meta's `X-Hub-Signature-256` over the body, under the app secret."""
        if body is None:
            return False
        return verify_signature(body.encode(), headers.get("x-hub-signature-256"), secret)

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Never: a webhook carries a batch, which the route reads with `parse_webhook`."""
        return None


def whatsapp_adapter() -> WhatsAppAdapter:
    """The registered adapter, or one registered now.

    The API registers it at startup; the job worker (`python -m app.worker`) never
    does, so code that will send from the worker - a trigger's result, a
    proactive message - asks for it here, as `teams_adapter()` is asked. Nothing
    calls it yet.
    """
    from app.services.channels import get_adapter, register_adapter

    try:
        adapter = get_adapter(WhatsAppAdapter.platform)
    except KeyError:
        adapter = WhatsAppAdapter()
        register_adapter(adapter)
    if not isinstance(adapter, WhatsAppAdapter):  # pragma: no cover - registered by platform
        raise TypeError("The adapter registered for WhatsApp is not the WhatsApp adapter")
    return adapter
