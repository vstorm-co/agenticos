"""iMessage through an explicitly configured company-owned BlueBubbles Mac."""

import base64
import secrets
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    ValidationError,
    field_validator,
)

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.services.channels import sms_prompts
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
    channel_key,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.imessage_transport import BridgeClient, BridgeCredentials
from app.services.channels.webhooks import inbound_webhook_url

PLATFORM = "imessage"
AUTH_HEADER = "authorization"
TAPBACK_REACTIONS = frozenset({"love", "like", "dislike", "laugh", "emphasize", "question"})


def chat_guid(value: str) -> str:
    parts = value.split(";")
    if (
        len(parts) != 3
        or parts[0] != "iMessage"
        or parts[1] not in ("-", "+")
        or not parts[2]
        or len(value) > 512
        or any(ord(char) < 32 or char == ":" for char in value)
    ):
        raise ValueError("A native iMessage chat GUID is required")
    return value


def _filename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].replace("\x00", "")[:255] or "attachment"


class _Handle(BaseModel):
    model_config = ConfigDict(strict=True)
    address: str = Field(min_length=1, max_length=320)


class _Chat(BaseModel):
    model_config = ConfigDict(strict=True)
    guid: str
    participants: list[_Handle] = Field(default_factory=list, max_length=1000)

    _valid_guid = field_validator("guid")(chat_guid)


class _Attachment(BaseModel):
    model_config = ConfigDict(strict=True)
    guid: str = Field(min_length=1, max_length=512)
    transfer_name: str | None = Field(default=None, alias="transferName", max_length=1024)
    mime_type: str | None = Field(default=None, alias="mimeType", max_length=255)
    total_bytes: int | None = Field(default=None, alias="totalBytes", ge=0)


class _Message(BaseModel):
    model_config = ConfigDict(strict=True)
    guid: str = Field(min_length=1, max_length=512)
    text: str | None = Field(default=None, max_length=32768, pattern=r"^[^\x00]*$")
    is_from_me: bool = Field(alias="isFromMe")
    handle: _Handle | None = None
    chats: list[_Chat] = Field(min_length=1, max_length=1)
    attachments: list[_Attachment] = Field(default_factory=list, max_length=20)
    item_type: int = Field(default=0, alias="itemType")
    associated_message_type: int | None = Field(default=None, alias="associatedMessageType")


class _Envelope(BaseModel):
    model_config = ConfigDict(strict=True)
    type: Literal["new-message"]
    data: _Message


class _Accepted(BaseModel):
    model_config = ConfigDict(strict=True)
    status: int = Field(ge=200, le=299)


class _Sent(BaseModel):
    model_config = ConfigDict(strict=True)
    guid: str = Field(min_length=1, max_length=512)
    error: int | None = None


class _SentResponse(_Accepted):
    data: _Sent


class _Webhook(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(gt=0)
    url: SecretStr


class _WebhookResponse(_Accepted):
    data: _Webhook


class _WebhooksResponse(_Accepted):
    data: list[_Webhook] = Field(max_length=1000)


class _ChatResponse(_Accepted):
    data: _Chat


def _callback_target(url: str, secret: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ChannelNotConfigured(
            message="The iMessage callback needs a plain public HTTP endpoint"
        )
    return urlunsplit(parts._replace(netloc=f"agenticos:{quote(secret, safe='')}@{parts.netloc}"))


def _same_callback(value: str, expected: str) -> bool:
    try:
        actual, target = urlsplit(value), urlsplit(expected)
        actual_endpoint = (actual.scheme, actual.hostname, actual.port, actual.path)
        expected_endpoint = (target.scheme, target.hostname, target.port, target.path)
    except ValueError:
        return False
    return actual_endpoint == expected_endpoint


class ImessageAdapter(ChannelAdapter):
    """The shared channel contract; BlueBubbles owns only the Mac transport."""

    platform = PLATFORM

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._bridge = BridgeClient(transport)

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        raise ChannelNotConfigured(message="iMessage requires its authenticated bridge webhook")

    async def stop_polling(self, bot_id: str) -> None:
        return

    async def aclose(self) -> None:
        await self._bridge.close()

    @staticmethod
    def _credentials(token: str, endpoint: str | None = None) -> BridgeCredentials:
        credentials = BridgeCredentials.decode(token)
        if endpoint is not None and httpx.URL(endpoint.rstrip("/")) != httpx.URL(
            str(credentials.server).rstrip("/")
        ):
            raise ChannelNotConfigured(
                message="The iMessage bridge endpoint changed; review its connection"
            )
        return credentials

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        credentials = self._credentials(bot_token, msg.api_base_url)
        target = chat_guid(channel_key(msg.platform_chat_id))
        files = list(msg.attachments)
        if msg.image_png is not None:
            files.insert(
                0,
                OutgoingAttachment(
                    filename=msg.image_filename, content=msg.image_png, mime_type="image/png"
                ),
            )
        if not msg.text.strip() and not files:
            raise ValueError("An iMessage needs text or a file")
        if any(
            not item.content or len(item.content) > settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
            for item in files
        ):
            raise ValueError("An iMessage attachment must fit the upload limit and contain data")
        if msg.text.strip():
            sent = await self._bridge.json_request(
                credentials,
                "POST",
                "/api/v1/message/text",
                _SentResponse,
                body={
                    "chatGuid": target,
                    "tempGuid": str(uuid4()),
                    "method": "apple-script",
                    "message": msg.text,
                },
            )
            self._require_send(sent)
        for item in files:
            name = _filename(item.filename)
            sent = await self._bridge.json_request(
                credentials,
                "POST",
                "/api/v1/message/attachment",
                _SentResponse,
                form={
                    "chatGuid": target,
                    "tempGuid": str(uuid4()),
                    "method": "apple-script",
                    "name": name,
                },
                files={"attachment": (name, item.content, item.mime_type)},
            )
            self._require_send(sent)

    @staticmethod
    def _require_send(response: _SentResponse) -> None:
        if response.data.error not in (None, 0):
            raise ExternalServiceError(
                message="The iMessage bridge reported a message delivery error",
                details={"bridge_code": response.data.error},
            )

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        credentials = self._credentials(bot_token)
        if not attachment.handle or len(attachment.handle) > 512:
            raise ValueError("An iMessage attachment GUID is required")
        limit = settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if attachment.size > limit:
            raise ValueError("The iMessage attachment exceeds the upload limit")
        return await self._bridge.download(
            credentials,
            f"/api/v1/attachment/{quote(attachment.handle, safe='')}/download",
            limit=limit,
        )

    async def send_prompt(self, bot_token: str, prompt: PromptMessage) -> None:
        start = await sms_prompts.reserve(
            prompt.bot_id, prompt.platform_chat_id, len(prompt.choices), platform=PLATFORM
        )
        lines = [f"{number}. {choice.label}" for number, choice in enumerate(prompt.choices, start)]
        await self.send_message(
            bot_token,
            OutgoingMessage(
                platform_chat_id=prompt.platform_chat_id,
                text=f"{prompt.text}\n\n" + "\n".join(lines) + "\n\nReply with just the number.",
            ),
        )
        await sms_prompts.remember(
            prompt.bot_id,
            prompt.platform_chat_id,
            [choice.value for choice in prompt.choices],
            start=start,
            platform=PLATFORM,
        )

    async def settle_prompt(self, bot_token: str, press: IncomingPress, text: str) -> None:
        await sms_prompts.settle(
            press.bot_id, press.platform_chat_id, press.value, platform=PLATFORM
        )
        await self.send_message(
            bot_token, OutgoingMessage(platform_chat_id=press.platform_chat_id, text=text)
        )

    async def acknowledge_message(
        self, bot_token: str, incoming: IncomingMessage, reaction: str
    ) -> None:
        if incoming.message_id is None:
            return
        reaction = "emphasize" if reaction == "eyes" else reaction
        if reaction not in TAPBACK_REACTIONS:
            raise ValueError("Choose a supported iMessage tapback")
        credentials = self._credentials(bot_token)
        await self._bridge.json_request(
            credentials,
            "POST",
            "/api/v1/message/react",
            _Accepted,
            body={
                "chatGuid": chat_guid(channel_key(incoming.platform_chat_id)),
                "selectedMessageGuid": incoming.message_id,
                "reaction": reaction,
                "partIndex": 0,
            },
        )

    async def is_channel_member(
        self, bot_token: str, channel_id: str, platform_user_id: str, *, api_base_url: str | None
    ) -> bool:
        credentials = self._credentials(bot_token, api_base_url)
        target = chat_guid(channel_key(channel_id))
        if target.startswith("iMessage;-;"):
            return (
                target.removeprefix("iMessage;-;").casefold() == platform_user_id.strip().casefold()
            )
        found = await self._bridge.json_request(
            credentials,
            "GET",
            f"/api/v1/chat/{quote(target, safe='')}?with=participants",
            _ChatResponse,
        )
        if found.data.guid != target:
            raise ExternalServiceError(message="The iMessage bridge returned another chat")
        return any(
            member.address.strip().casefold() == platform_user_id.strip().casefold()
            for member in found.data.participants
        )

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        credentials = self._credentials(bot_token)
        if secret is None:
            raise ChannelNotConfigured(
                message="The iMessage callback needs its vault-sealed secret"
            )
        target = _callback_target(url, secret)
        created = await self._bridge.json_request(
            credentials,
            "POST",
            "/api/v1/webhook",
            _WebhookResponse,
            body={"url": target, "events": ["new-message"]},
        )
        if not secrets.compare_digest(created.data.url.get_secret_value(), target):
            raise ExternalServiceError(
                message="The iMessage bridge registered a different callback"
            )
        return True

    async def delete_webhook(self, bot_token: str) -> bool:
        credentials = self._credentials(bot_token)
        target = inbound_webhook_url(PLATFORM, credentials.bot_id)
        hooks = await self._bridge.json_request(
            credentials, "GET", "/api/v1/webhook", _WebhooksResponse
        )
        for hook in hooks.data:
            if _same_callback(hook.url.get_secret_value(), target):
                await self._bridge.json_request(
                    credentials, "DELETE", f"/api/v1/webhook/{hook.id}", _Accepted
                )
        return True

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        expected = "Basic " + base64.b64encode(f"agenticos:{secret}".encode()).decode("ascii")
        supplied = headers.get(AUTH_HEADER, "")
        return supplied.isascii() and secrets.compare_digest(supplied, expected)

    def parse_incoming(
        self, raw_payload: dict[str, JsonValue], bot_id: str
    ) -> IncomingMessage | None:
        if raw_payload.get("type") != "new-message":
            return None
        try:
            event = _Envelope.model_validate(raw_payload)
        except ValidationError:
            raise ExternalServiceError(
                message="The iMessage bridge sent an invalid message envelope"
            ) from None
        message = event.data
        if (
            message.is_from_me
            or message.item_type != 0
            or message.associated_message_type not in (None, 0)
        ):
            return None
        if message.handle is None or not message.handle.address.strip():
            raise ExternalServiceError(message="The iMessage bridge did not identify its sender")
        target = message.chats[0].guid
        sender = message.handle.address.strip().casefold()
        private = target.startswith("iMessage;-;")
        if private and target.removeprefix("iMessage;-;").strip().casefold() != sender:
            raise ExternalServiceError(
                message="The iMessage private chat does not match its sender"
            )
        text = message.text or ""
        attachments = [
            IncomingAttachment(
                filename=_filename(item.transfer_name or item.guid),
                mime_type=item.mime_type or "application/octet-stream",
                size=item.total_bytes or 0,
                handle=item.guid,
            )
            for item in message.attachments
        ]
        if not text.strip() and not attachments:
            return None
        return IncomingMessage(
            platform=PLATFORM,
            bot_id=bot_id,
            platform_user_id=sender,
            platform_chat_id=target,
            chat_type="private" if private else "group",
            text=text,
            raw=event.model_dump(mode="json", by_alias=True),
            platform_username=sender,
            message_id=message.guid,
            addressed=private,
            attachments=attachments,
        )
