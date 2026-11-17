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
from typing import Any, Literal, NoReturn
from urllib.parse import urlparse

import httpx
import logfire

from app.core.exceptions import ExternalServiceError
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.whatsapp_templates import LateTemplate

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

MEDIA_HOSTS: frozenset[str] = frozenset({"lookaside.fbsbx.com"})
"""The only hosts a media download may reach. A media URL comes out of a payload, so it
is checked before the token is sent anywhere."""

CLOSED_WINDOW_CODE = 131047
"""Meta refusing a free-form message because the customer's 24-hour window is closed."""

TEMPLATE_PAGES = 5
"""The most pages of the template listing read; an account has a handful of templates."""

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


def is_template_refusal(code: int | None) -> bool:
    """Whether Graph's code is one of the template errors (132000-132999); for logging only."""
    return code is not None and 132000 <= code <= 132999


class WhatsAppWindowClosed(WhatsAppGraphError):
    """A message needs the 24-hour window and no late-answer template could carry it."""

    message = (
        "Outside WhatsApp's 24-hour window, and no late-answer template could carry this message"
    )

    def __init__(self) -> None:
        super().__init__(code=CLOSED_WINDOW_CODE)


class WhatsAppWindowUnavailable(WhatsAppGraphError):
    """The record behind the 24-hour window could not be read or written, so a late message could not be held."""

    message = "WhatsApp's 24-hour window record is unavailable, so the message could not be held"

    def __init__(self) -> None:
        super().__init__(code=None)


class WhatsAppMediaTooLarge(WhatsAppGraphError):
    """A downloaded file is bigger than the caller allows."""

    message = "The file is too large"


class WhatsAppTokenRefused(ChannelNotConfigured):
    """The access token is expired, revoked or lacks the asset: the operator must replace it."""

    message = TOKEN_REFUSED

    def __init__(self, *, code: int) -> None:
        super().__init__(details={"code": code})


@dataclass(frozen=True)
class MediaInfo:
    """Where a customer's file can be fetched, and what Meta says it is."""

    url: str = field(repr=False)
    mime_type: str | None
    file_size: int | None


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

        Only the envelope's shape is checked: a field that is present but empty
        reads back as empty, as it does for a bot row with no phone number id.

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
        callback: str | None = None,
    ) -> str:
        """Send a text message to a business-scoped user id; returns the new wamid.

        `recipient` (not `to`) addresses a BSUID, which carries no phone number.
        `callback` is echoed on the message's status webhooks (the run it belongs to).

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, or a reply with no message id.
        """
        return await self._send(
            creds,
            self._envelope(
                recipient,
                "text",
                {"body": body, "preview_url": False},
                reply_to=reply_to,
                callback=callback,
            ),
        )

    async def send_media(
        self,
        creds: WhatsAppCredentials,
        *,
        recipient: str,
        kind: Literal["image", "document"],
        media_id: str,
        caption: str | None,
        filename: str | None,
        reply_to: str | None,
        callback: str | None = None,
    ) -> str:
        """Send an uploaded file as an image or a document; returns the new wamid.

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, or a reply with no message id.
        """
        media: dict[str, Any] = {"id": media_id}
        if caption:
            media["caption"] = caption
        if filename and kind == "document":
            media["filename"] = filename
        return await self._send(
            creds, self._envelope(recipient, kind, media, reply_to=reply_to, callback=callback)
        )

    async def send_interactive(
        self,
        creds: WhatsAppCredentials,
        *,
        recipient: str,
        interactive: dict[str, Any],
        reply_to: str | None = None,
        callback: str | None = None,
    ) -> str:
        """Send reply buttons or a list; returns the new wamid.

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, or a reply with no message id.
        """
        return await self._send(
            creds,
            self._envelope(
                recipient, "interactive", interactive, reply_to=reply_to, callback=callback
            ),
        )

    async def send_template(
        self,
        creds: WhatsAppCredentials,
        *,
        recipient: str,
        template: LateTemplate,
        text: str,
        callback: str | None = None,
    ) -> str:
        """Send `text` as the one parameter of the late-answer template; returns the new wamid.

        A template may go out outside the 24-hour window. The caller flattens `text`:
        Meta's parameters refuse line breaks and tabs.

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, or a reply with no message id.
        """
        parameter: dict[str, str] = {"type": "text", "text": text}
        if template.parameter_name:
            parameter["parameter_name"] = template.parameter_name
        content = {
            "name": template.name,
            "language": {"code": template.language},
            "components": [{"type": "body", "parameters": [parameter]}],
        }
        return await self._send(
            creds, self._envelope(recipient, "template", content, reply_to=None, callback=callback)
        )

    async def message_templates(
        self, creds: WhatsAppCredentials, *, account_id: str
    ) -> list[dict[str, Any]]:
        """List the account's message templates, at most `TEMPLATE_PAGES` pages.

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, or an id that is not a Graph id
                (no request is made).
        """
        if not (account_id.isascii() and account_id.isdigit()):
            self._refused(creds, None)
        params = {"fields": "name,category,status,language,components", "limit": "100"}
        listing: list[dict[str, Any]] = []
        for _ in range(TEMPLATE_PAGES):
            page = await self._call(creds, "GET", f"/{account_id}/message_templates", params=params)
            data = page.get("data")
            listing += (
                [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
            )
            paging = page.get("paging")
            paging = paging if isinstance(paging, dict) else {}
            cursors = paging.get("cursors")
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not paging.get("next") or not isinstance(after, str) or not after:
                break
            params = {**params, "after": after}
        return listing

    async def media_info(self, creds: WhatsAppCredentials, *, media_id: str) -> MediaInfo:
        """Look up the URL and type of a file a customer sent.

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, an id that is not a Graph media
                id (no request is made), or a reply with no URL.
        """
        if not (media_id.isascii() and media_id.isdigit()):
            self._refused(creds, None)
        # The path holds the media id, which tracing exports whole.
        with logfire.suppress_instrumentation():
            found = await self._call(creds, "GET", f"/{media_id}")
        url = found.get("url")
        if not isinstance(url, str) or not url:
            self._refused(creds, None)
        mime_type = found.get("mime_type")
        size = found.get("file_size")
        return MediaInfo(
            url=url,
            mime_type=mime_type if isinstance(mime_type, str) else None,
            file_size=_byte_count(size),
        )

    async def download_media(self, creds: WhatsAppCredentials, *, url: str, limit: int) -> bytes:
        """Fetch a file from Meta's media host, never more than `limit` bytes.

        Raises:
            WhatsAppMediaTooLarge: More than `limit` bytes arrived.
            WhatsAppGraphError: The URL is not https on a media host, or the
                fetch failed. A redirect is a failure: it would carry the token
                to a host nobody checked.
        """
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in MEDIA_HOSTS:
            self._refused(creds, None)
        headers = {"Authorization": f"Bearer {creds.access_token}", "Accept-Encoding": "identity"}
        received = bytearray()
        # The URL is Meta's, and tracing exports a request's URL whole.
        with logfire.suppress_instrumentation():
            try:
                async with self._client.stream(
                    "GET", url, headers=headers, follow_redirects=False
                ) as response:
                    if not response.is_success:
                        self._refused(creds, None)
                    async for chunk in response.aiter_bytes():
                        received += chunk
                        if len(received) > limit:
                            raise WhatsAppMediaTooLarge(code=None)
            except httpx.HTTPError:
                self._refused(creds, None)
        return bytes(received)

    async def upload_media(
        self, creds: WhatsAppCredentials, *, content: bytes, mime_type: str, filename: str
    ) -> str:
        """Upload a file to send later; returns its media id.

        Raises:
            WhatsAppTokenRefused: Meta refused the token.
            WhatsAppGraphError: Any other refusal, or a reply with no id.
        """
        reply = await self._call(
            creds,
            "POST",
            f"/{creds.phone_number_id}/media",
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (filename, content, mime_type)},
        )
        media_id = reply.get("id")
        if not isinstance(media_id, str) or not media_id:
            self._refused(creds, None)
        return media_id

    @staticmethod
    def _envelope(
        recipient: str,
        kind: str,
        content: dict[str, Any],
        *,
        reply_to: str | None,
        callback: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "recipient": recipient,
            "type": kind,
            kind: content,
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        if callback:
            # ASSUMPTION (Meta): echoed on this message's status webhooks, so a failed
            # status names the run it belongs to.
            payload["biz_opaque_callback_data"] = callback
        return payload

    async def _send(self, creds: WhatsAppCredentials, payload: dict[str, Any]) -> str:
        reply = await self._post(creds, payload)
        messages = reply.get("messages")
        wamid = messages[0].get("id") if isinstance(messages, list) and messages else None
        if not isinstance(wamid, str) or not wamid:
            self._refused(creds, None)
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
        return await self._call(creds, "POST", f"/{creds.phone_number_id}/messages", body=payload)

    async def _call(
        self,
        creds: WhatsAppCredentials,
        method: Literal["GET", "POST"],
        path: str,
        *,
        body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """One Graph call with the retry rules.

        A POST is retried only where the request provably never reached Meta
        (`RETRYABLE_TRANSPORT`) or Meta said to retry: a repeat could send twice.
        A GET changes nothing, so it retries a read timeout too.
        """
        url = f"{GRAPH_BASE}/{GRAPH_VERSION}{path}"
        headers = {"Authorization": f"Bearer {creds.access_token}"}
        retryable = httpx.TransportError if method == "GET" else RETRYABLE_TRANSPORT
        if method == "GET":
            headers["Accept-Encoding"] = "identity"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last = attempt == MAX_ATTEMPTS
            try:
                response = await self._client.request(
                    method, url, headers=headers, json=body, data=data, files=files, params=params
                )
            except retryable:
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


def _byte_count(value: object) -> int | None:
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


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
