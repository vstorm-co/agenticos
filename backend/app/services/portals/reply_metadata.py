"""Bounded, body-free mail metadata for a durable awaited reply.

The reader never follows message-supplied URLs or downloads attachments. Gmail's
thread id and Graph's conversation id are provider scopes; RFC reply headers are
additional sender claims, never authorization to execute an action.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Literal, Protocol
from urllib.parse import quote

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.core.exceptions import ExternalServiceError
from app.services.portals.mail_auth import authenticated
from app.services.portals.mail_thread import MAX_ID_CHARS, thread_headers

MailProvider = Literal["google", "outlook"]
MAX_MESSAGES = 500
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ReplyMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(min_length=1, max_length=2048, pattern=r"^[^\x00-\x1f\x7f]+$")
    thread_id: str = Field(min_length=1, max_length=2048, pattern=r"^[^\x00-\x1f\x7f]+$")
    sender: str = Field(max_length=320, pattern=r"^[^\x00-\x1f\x7f]*$")
    received_at: AwareDatetime
    rfc_message_id: str = Field(default="", max_length=MAX_ID_CHARS, pattern=r"^[^\x00-\x1f\x7f]*$")
    in_reply_to: str = Field(default="", max_length=MAX_ID_CHARS, pattern=r"^[^\x00-\x1f\x7f]*$")
    references: tuple[str, ...] = Field(default=(), max_length=20)
    authenticated: bool
    automatic: bool = False
    sent_or_draft: bool = False


class ReplyMetadataReader(Protocol):
    async def read(
        self,
        *,
        provider: MailProvider,
        access_token: SecretStr,
        thread_id: str,
        not_before: datetime,
        mailbox: str | None = None,
    ) -> tuple[ReplyMessage, ...]: ...


class _Header(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str = Field(max_length=255)
    value: str = Field(max_length=32768)


class _GooglePart(BaseModel):
    headers: list[_Header] = Field(default_factory=list, max_length=512)


class _GoogleMessage(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str
    threadId: str
    internalDate: str = Field(pattern=r"^[0-9]{1,16}$")
    labelIds: list[str] = Field(default_factory=list, max_length=100)
    payload: _GooglePart


class _GoogleThread(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str
    messages: list[_GoogleMessage] = Field(default_factory=list, max_length=MAX_MESSAGES)


class _Address(BaseModel):
    address: str = Field(max_length=320)


class _Sender(BaseModel):
    emailAddress: _Address


class _GraphMessage(BaseModel):
    model_config = ConfigDict(strict=True)
    id: str
    conversationId: str
    receivedDateTime: AwareDatetime
    sender: _Sender = Field(alias="from")
    internetMessageId: str = Field(default="", max_length=MAX_ID_CHARS)
    internetMessageHeaders: list[_Header] = Field(default_factory=list, max_length=512)
    isDraft: bool = False
    parentFolderId: str


class _GraphFolder(BaseModel):
    id: str = Field(min_length=1, max_length=2048)


class _GraphPage(BaseModel):
    value: list[_GraphMessage] = Field(max_length=MAX_MESSAGES)
    next_link: str | None = Field(default=None, alias="@odata.nextLink", max_length=8192)


def _metadata(
    *,
    message_id: str,
    thread_id: str,
    sender: str,
    received_at: datetime,
    headers: list[_Header],
    sent_or_draft: bool,
    internal: bool = False,
) -> ReplyMessage:
    pairs = [(header.name, header.value) for header in headers]
    threaded = thread_headers(pairs)
    first: dict[str, str] = {}
    for name, value in pairs:
        first.setdefault(name.casefold(), value.strip())
    content_type = first.get("content-type", "").casefold()
    automatic = first.get("auto-submitted", "").casefold() not in (
        "",
        "no",
    ) or content_type.startswith(
        ("message/delivery-status", "message/disposition-notification", "multipart/report")
    )
    return ReplyMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender=parseaddr(sender)[1].strip().casefold(),
        received_at=received_at,
        rfc_message_id=threaded["rfc_message_id"],
        in_reply_to=threaded["in_reply_to"],
        references=tuple(threaded["references"]),
        authenticated=authenticated(pairs, sender) or internal,
        automatic=automatic,
        sent_or_draft=sent_or_draft,
    )


class MailReplyMetadataClient:
    """One pooled HTTP client; no retries or transport fallback can disguise a failed check."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            transport=transport, timeout=10, follow_redirects=False, trust_env=False
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get[T: BaseModel](
        self,
        url: str,
        *,
        token: SecretStr,
        schema: type[T],
        params: Mapping[str, str] | None = None,
    ) -> T:
        async with self._http.stream(
            "GET",
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token.get_secret_value()}",
                "Accept": "application/json",
                "Prefer": 'IdType="ImmutableId"',
            },
        ) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ExternalServiceError(
                        message="The mail thread metadata exceeds its size limit"
                    )
                content.extend(chunk)
        return schema.model_validate_json(content)

    async def read(
        self,
        *,
        provider: MailProvider,
        access_token: SecretStr,
        thread_id: str,
        not_before: datetime,
        mailbox: str | None = None,
    ) -> tuple[ReplyMessage, ...]:
        try:
            async with asyncio.timeout(20):
                if provider == "google":
                    return await self._google(access_token, thread_id)
                return await self._outlook(access_token, thread_id, not_before, mailbox)
        except httpx.HTTPError, ValidationError, TimeoutError, OverflowError, OSError, ValueError:
            raise ExternalServiceError(
                message="The mailbox could not be checked; no reply verdict was recorded"
            ) from None

    async def _google(self, token: SecretStr, thread_id: str) -> tuple[ReplyMessage, ...]:
        thread = await self._get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{quote(thread_id, safe='')}",
            token=token,
            schema=_GoogleThread,
            params={
                "format": "metadata",
                "fields": "id,messages(id,threadId,internalDate,labelIds,payload/headers)",
            },
        )
        if thread.id != thread_id or any(
            message.threadId != thread_id for message in thread.messages
        ):
            raise ExternalServiceError(message="The mailbox returned another thread")
        results: list[ReplyMessage] = []
        for message in thread.messages:
            sender = next(
                (
                    header.value
                    for header in message.payload.headers
                    if header.name.casefold() == "from"
                ),
                "",
            )
            results.append(
                _metadata(
                    message_id=message.id,
                    thread_id=message.threadId,
                    sender=sender,
                    received_at=datetime.fromtimestamp(int(message.internalDate) / 1000, UTC),
                    headers=message.payload.headers,
                    sent_or_draft=bool({"SENT", "DRAFT"}.intersection(message.labelIds)),
                )
            )
        return tuple(results)

    async def _outlook(
        self,
        token: SecretStr,
        thread_id: str,
        not_before: datetime,
        mailbox: str | None,
    ) -> tuple[ReplyMessage, ...]:
        place = "me" if mailbox is None else f"users/{quote(mailbox, safe='')}"
        base = f"https://graph.microsoft.com/v1.0/{place}/messages"
        sent = await self._get(
            f"https://graph.microsoft.com/v1.0/{place}/mailFolders/sentitems",
            token=token,
            schema=_GraphFolder,
            params={"$select": "id"},
        )
        escaped = thread_id.replace("'", "''")
        params = {
            "$filter": f"conversationId eq '{escaped}' and receivedDateTime ge {not_before.astimezone(UTC).isoformat()}",
            "$select": "id,conversationId,from,receivedDateTime,internetMessageId,internetMessageHeaders,isDraft,parentFolderId",
            "$top": "100",
        }
        page = await self._get(base, token=token, schema=_GraphPage, params=params)
        results: list[ReplyMessage] = []
        page_number = 0
        while True:
            for message in page.value:
                if message.conversationId != thread_id:
                    raise ExternalServiceError(message="The mailbox returned another thread")
                headers = message.internetMessageHeaders
                if not any(header.name.casefold() == "message-id" for header in headers):
                    headers = [
                        *headers,
                        _Header(name="Message-ID", value=message.internetMessageId),
                    ]
                internal = next(
                    (
                        header.value.strip().casefold() == "internal"
                        for header in headers
                        if header.name.casefold() == "x-ms-exchange-organization-authas"
                    ),
                    False,
                )
                results.append(
                    _metadata(
                        message_id=message.id,
                        thread_id=message.conversationId,
                        sender=message.sender.emailAddress.address,
                        received_at=message.receivedDateTime,
                        headers=headers,
                        sent_or_draft=message.isDraft or message.parentFolderId == sent.id,
                        internal=internal,
                    )
                )
            if len(results) > MAX_MESSAGES:
                raise ExternalServiceError(message="The mail thread exceeds its message limit")
            if page.next_link is None:
                return tuple(results)
            page_number += 1
            if page_number >= 5:
                raise ExternalServiceError(message="The mail thread exceeds its page limit")
            target = httpx.URL(page.next_link)
            original = httpx.URL(base)
            if (
                target.scheme != "https"
                or target.host != original.host
                or target.port != original.port
                or target.path != original.path
                or target.userinfo
                or target.fragment
            ):
                raise ExternalServiceError(message="The mailbox returned an unsafe continuation")
            page = await self._get(page.next_link, token=token, schema=_GraphPage)
