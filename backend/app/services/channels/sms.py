"""SMS through Twilio, as a channel platform (#2082).

A person texts the number; the message reaches an agent exactly like a direct
message on any other platform: through the same router, the same linked identity,
the same access policy and the same budgets. This module is only the transport.

**Credentials.** One bot is one Twilio number. Its token is
`ACCOUNT_SID:AUTH_TOKEN:+15551234567` - the account, the secret that both signs
inbound requests and authorizes outbound ones, and the number it sends from -
sealed in the vault like any other bot token. There is no webhook secret: Twilio
signs every request with the auth token itself.

**Inbound** is authenticated by Twilio's request signature and nothing else: HMAC-SHA1
over the full URL the request was addressed to plus its form fields in key order,
base64-encoded (`twilio_signature`). A valid signature proves the request came from
Twilio for this account. It is *not* proof of who the sender is: the sender's number
is a claim, so a person acts with their AgenticOS permissions only once they have
linked that number to their account through the ordinary channel link.

**Outbound** is one REST call per message. An answer is cut to what one SMS thread
carries and says where the rest is, rather than arriving as a dozen segments.

SMS cannot stream or edit a message, so an answer is one finished message. It cannot press
a button either, so a prompt is sent as numbered lines and the webhook turns a lone digit
that fits back into the press it stands for (`sms_prompts`).
"""

import base64
import hashlib
import hmac
import logging
import re
from typing import Any
from urllib.parse import parse_qsl

import httpx

from app.services.channels import sms_prompts
from app.services.channels.base import (
    ChannelAdapter,
    IncomingMessage,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.exceptions import ChannelNotConfigured

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com"
SIGNATURE_HEADER = "x-twilio-signature"
SIGNED_URL_HEADER = "x-agenticos-signed-url"
"""The address Twilio signed, which only the route knows: the adapter is one object
serving every bot and the URL names the bot, so the route hands it in with the
headers instead of the adapter guessing it from a proxied `Host`."""

MAX_CHARS = 1500
"""Roughly ten segments: enough for a real answer, short of a bill nobody asked for."""

MORE_IN_THE_APP = "… (the rest is in AgenticOS)"


def twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """The signature Twilio puts on a request to `url` with these form fields.

    The URL as addressed, then every field as `key + value` in key order, signed with
    HMAC-SHA1 under the auth token and base64-encoded - Twilio's published algorithm.
    """
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def split_credentials(token: str) -> tuple[str, str, str]:
    """`(account_sid, auth_token, from_number)` from a bot's token.

    Raises:
        ChannelNotConfigured: The token is not `SID:TOKEN:NUMBER`. An operator has to
            fix it; no retry will.
    """
    parts = token.split(":")
    if (
        len(parts) != 3
        or not all(parts)
        or not parts[0].startswith("AC")
        or not parts[2].startswith("+")
    ):
        raise ChannelNotConfigured(
            "An SMS bot's token is ACCOUNT_SID:AUTH_TOKEN:+NUMBER - the Twilio account, "
            "its auth token and the number it sends from."
        )
    return parts[0], parts[1], parts[2]


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_MARKUP = re.compile(r"(\*\*|__|`+|^#{1,6}\s+|^>\s+)", re.M)


def plain(text: str) -> str:
    """Markdown as a phone shows it: no markers, a link as its text and its address."""
    return _MARKUP.sub("", _LINK.sub(r"\1 (\2)", text))


def fit_to_sms(text: str) -> str:
    """The answer as plain text, cut where one SMS thread ends and saying so."""
    text = plain(text).strip()
    if len(text) <= MAX_CHARS:
        return text
    return text[: MAX_CHARS - len(MORE_IN_THE_APP)].rstrip() + MORE_IN_THE_APP


class SmsAdapter(ChannelAdapter):
    platform = "sms"

    def __init__(self, *, api: str = TWILIO_API) -> None:
        self._api = api
        self._client = httpx.AsyncClient(timeout=15.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send one text to the sender's number.

        Raises:
            ChannelNotConfigured: The bot's token is malformed.
            httpx.HTTPStatusError: Twilio refused it; the router records the failure.
        """
        sid, auth_token, from_number = split_credentials(bot_token)
        body = fit_to_sms(msg.text)
        if not body:
            return
        response = await self._client.post(
            f"{self._api}/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, auth_token),
            data={"To": msg.platform_chat_id, "From": from_number, "Body": body},
        )
        response.raise_for_status()

    async def send_prompt(self, bot_token: str, prompt: PromptMessage) -> None:
        """Send the question with its choices numbered, and remember what each number means.

        There are no buttons to press, so the person replies with a digit; the router
        reads it back through `sms_prompts.answer`.
        """
        start = await sms_prompts.first_number(prompt.bot_id, prompt.platform_chat_id)
        lines = [f"{number}. {choice.label}" for number, choice in enumerate(prompt.choices, start)]
        await self.send_message(
            bot_token,
            OutgoingMessage(
                platform_chat_id=prompt.platform_chat_id,
                text=f"{prompt.text}\n" + "\n".join(lines) + "\nReply with the number.",
            ),
        )
        # After the send: a prompt that never arrived must not stay answerable.
        await sms_prompts.remember(
            prompt.bot_id,
            prompt.platform_chat_id,
            [choice.value for choice in prompt.choices],
            start=start,
        )

    async def settle_prompt(self, bot_token: str, press: IncomingPress, text: str) -> None:
        """The prompt is decided: a later digit from this number is a message again.

        Not called for a choice in a multi-select that is still open, which is why the
        mapping outlives the first reply.
        """
        await sms_prompts.settle(press.bot_id, press.platform_chat_id, press.value)

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """SMS only ever arrives by webhook; there is nothing to poll."""

    async def stop_polling(self, bot_id: str) -> None:
        return None

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """Twilio's number takes its webhook in the console; the operator pastes `url` there."""
        logger.info("Point the Twilio number's incoming-message webhook at %s", url)
        return True

    async def delete_webhook(self, bot_token: str) -> bool:
        return True

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Whether Twilio signed this request, with `secret` being the auth token.

        Compared in constant time. A request with no signature, no body or no signed URL
        is not Twilio's.
        """
        given = headers.get(SIGNATURE_HEADER)
        url = headers.get(SIGNED_URL_HEADER)
        if not given or not url or body is None:
            return False
        params = dict(parse_qsl(body, keep_blank_values=True))
        return hmac.compare_digest(given, twilio_signature(url, params, secret))

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """A text from a number. Media-only messages and empty ones are ignored."""
        sender = str(raw_payload.get("From") or "")
        text = str(raw_payload.get("Body") or "").strip()
        if not sender or not text:
            return None
        return IncomingMessage(
            platform=self.platform,
            bot_id=bot_id,
            platform_user_id=sender,
            platform_chat_id=sender,
            chat_type="private",
            text=text,
            raw=raw_payload,
            message_id=str(raw_payload.get("MessageSid") or "") or None,
            addressed=True,
        )
