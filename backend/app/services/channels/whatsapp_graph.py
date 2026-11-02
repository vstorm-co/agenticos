"""WhatsApp Cloud API: the credentials a bot sends with, and the Graph client (#2076).

`WhatsAppCredentials` is the envelope the rest of the channel layer passes around
as the bot's "token". `WhatsAppGraph` is the only code that talks to Meta.

Nothing Graph says is ever kept: a response body or an httpx exception can carry
a customer's phone number or a fragment of the token, so a failure is reduced to
its numeric `code` and everything else is dropped.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, NoReturn

import httpx

from app.core.exceptions import ExternalServiceError
from app.services.channels.exceptions import ChannelNotConfigured

logger = logging.getLogger(__name__)

GRAPH_VERSION = "v26.0"
GRAPH_BASE = "https://graph.facebook.com"

AUTH_CODES = frozenset({0, 3, 10, 190, 200, 131005})
"""Meta refusing the token itself, or what it may reach: only the operator can fix it."""

RETRYABLE_CODES = frozenset({2, 4, 80007, 130429, 131000, 131056, 131057})
"""Rate limits and transient faults."""

RETRYABLE_TRANSPORT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
"""Failures where the request provably never reached Meta. `ReadTimeout`, `ReadError`,
`WriteTimeout` and `RemoteProtocolError` are not here: the message may have landed,
and a retry would send it twice."""

MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1, 2)
_TIMEOUT = httpx.Timeout(15.0)

TOKEN_REFUSED = (
    "Meta refused this bot's access token. Create a permanent System User token in "
    "Meta Business Settings and paste it into the bot."
)


class WhatsAppGraphError(ExternalServiceError):
    """Meta did not accept a call. Carries Graph's numeric `code` and nothing it said."""

    message = "WhatsApp did not accept the message"

    def __init__(self, *, code: int | None) -> None:
        super().__init__(details={"code": code})


class WhatsAppTokenRefused(ChannelNotConfigured):
    """The access token is expired, revoked or lacks the asset: the operator must replace it."""

    message = TOKEN_REFUSED

    def __init__(self, *, code: int) -> None:
        super().__init__(details={"code": code})


@dataclass(frozen=True)
class WhatsAppCredentials:
    """A WhatsApp bot's access token and the number it sends from.

    Carried through the channel layer as the bot's "token" - one string, like
    every other platform's - so a reply and a download each have everything they
    need without a second lookup. `unseal_bot_token` composes it from the row;
    nothing else builds one from text. `bot_id` is there so send health can be
    attributed to the bot without the caller threading it alongside.
    """

    bot_id: str
    access_token: str = field(repr=False)
    phone_number_id: str

    def encode(self) -> str:
        return json.dumps(
            {
                "bot_id": self.bot_id,
                "access_token": self.access_token,
                "phone_number_id": self.phone_number_id,
            }
        )

    @classmethod
    def decode(cls, token: str) -> WhatsAppCredentials:
        """Read what `encode` wrote.

        Raises:
            ValueError: If the string is not an envelope `encode` wrote, for
                example one that is not JSON or lacks a field.
        """
        try:
            data = json.loads(token)
            return cls(
                bot_id=str(data["bot_id"]),
                access_token=str(data["access_token"]),
                phone_number_id=str(data["phone_number_id"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("A WhatsApp bot's credentials are not readable") from exc


class WhatsAppGraph:
    """Sends WhatsApp messages through the Cloud API."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_text(
        self,
        creds: WhatsAppCredentials,
        *,
        recipient: str,
        body: str,
        reply_to: str | None = None,
    ) -> str:
        """Send a text message to a business-scoped user id; returns the new wamid.

        `recipient` (not `to`) addresses a BSUID, which carries no phone number.

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, or a reply with no message id.
        """
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": recipient,
            "type": "text",
            "text": {"body": body, "preview_url": False},
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        reply = await self._post(creds, payload)
        messages = reply.get("messages")
        wamid = messages[0].get("id") if isinstance(messages, list) and messages else None
        if not isinstance(wamid, str) or not wamid:
            raise WhatsAppGraphError(code=None)
        return wamid

    async def mark_read(self, creds: WhatsAppCredentials, *, message_id: str, typing: bool) -> None:
        """Mark a customer's message read, and show "typing" while the answer is made."""
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if typing:
            payload["typing_indicator"] = {"type": "text"}
        await self._post(creds, payload)

    async def _post(self, creds: WhatsAppCredentials, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{creds.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {creds.access_token}"}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last = attempt == MAX_ATTEMPTS
            try:
                response = await self._client.post(url, json=payload, headers=headers)
            except RETRYABLE_TRANSPORT:
                if not last:
                    await asyncio.sleep(_BACKOFF_SECONDS[attempt - 1])
                    continue
                self._refused(creds, None)
            except httpx.HTTPError:
                self._refused(creds, None)
            if response.is_success:
                return _object(response)
            code = _error_code(response)
            if code in AUTH_CODES:
                self._refused(creds, code)
            if code in RETRYABLE_CODES and not last:
                await asyncio.sleep(_BACKOFF_SECONDS[attempt - 1])
                continue
            self._refused(creds, code)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _refused(creds: WhatsAppCredentials, code: int | None) -> NoReturn:
        logger.warning("whatsapp_graph_refused", extra={"bot_id": creds.bot_id, "code": code})
        # `from None` even where there is no active exception: the cause of a
        # transport failure carries the request URL and the customer in it.
        if code is not None and code in AUTH_CODES:
            raise WhatsAppTokenRefused(code=code) from None
        raise WhatsAppGraphError(code=code) from None


def _object(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_code(response: httpx.Response) -> int | None:
    error = _object(response).get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, int) and not isinstance(code, bool) else None
