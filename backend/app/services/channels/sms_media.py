"""Short-lived media handoff for Twilio's outbound MMS fetches.

Twilio fetches MediaUrl with GET and HEAD rather than accepting uploaded bytes.
Only bytes explicitly passed to the bound channel adapter are staged here, never
an arbitrary storage filename. Each handoff needs its own random credential and
expires in shared Redis; it survives an API/worker restart without publishing the
original attachment or opening an authenticated file route to the internet.
"""

import base64
import hashlib
import mimetypes
import re
import secrets
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Base64Bytes, BaseModel, ConfigDict

from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.services.channels.base import OutgoingAttachment
from app.services.channels.exceptions import ChannelNotConfigured

TTL_SECONDS = 15 * 60
MAX_BYTES = 5_000_000
MAX_OTHER_BYTES = 500_000
MAX_FILES = 10
_IMAGES = frozenset({"image/jpeg", "image/jpg", "image/png", "image/gif"})
_ACCEPTED = _IMAGES | {
    "image/heic",
    "image/heif",
    "image/tiff",
    "image/bmp",
    "video/mpeg4",
    "video/mp4",
    "video/mpeg",
    "video/webm",
    "video/quicktime",
    "video/3gpp",
    "video/3gpp2",
    "video/3gpp-tt",
    "video/h261",
    "video/h263",
    "video/h263-1998",
    "video/h263-2000",
    "video/h264",
    "video/h265",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/mp3",
    "audio/3gpp",
    "audio/3gpp2",
    "audio/basic",
    "audio/l24",
    "audio/vnd.rn-realaudio",
    "audio/vnd.wave",
    "audio/ac3",
    "audio/webm",
    "audio/amr-nb",
    "audio/amr",
    "text/vcard",
    "text/x-vcard",
    "text/directory",
    "text/csv",
    "text/richtext",
    "text/rtf",
    "text/calendar",
    "application/pdf",
}
_TOKEN = re.compile(r"[0-9a-f]{64}")


class StoredSmsMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    mime_type: str
    content: Base64Bytes
    token_hash: str


def _key(media_id: UUID) -> str:
    return f"channel:sms:outbound-media:{media_id}"


def validate_attachments(files: Sequence[OutgoingAttachment], *, text: str) -> None:
    """Twilio's MMS limits, before anything is stored or sent.

    https://www.twilio.com/docs/messaging/api/message-resource
    https://www.twilio.com/docs/messaging/guides/accepted-mime-types
    Other accepted formats have stricter carrier limits; this transport caps
    them at the Messages API's documented 500 KB rather than guessing a carrier.
    """
    if len(files) > MAX_FILES:
        raise ValueError("An MMS can contain at most ten files.")
    if sum(len(item.content) for item in files) + len(text.encode()) > MAX_BYTES:
        raise ValueError("An MMS, including its text and files, must fit within 5 MB.")
    for item in files:
        if item.mime_type not in _ACCEPTED:
            raise ValueError(f"MMS does not support the file type {item.mime_type}.")
        if not item.content:
            raise ValueError("An MMS file cannot be empty.")
        if item.mime_type not in _IMAGES and len(item.content) > MAX_OTHER_BYTES:
            raise ValueError("A non-JPEG/PNG/GIF MMS file must fit within 500 KB.")


class SmsMediaService:
    def __init__(self, redis: RedisClient) -> None:
        self.redis = redis

    async def stage(self, file: OutgoingAttachment) -> str:
        """A fetch credential for these bytes only; never returned to the model."""
        validate_attachments([file], text="")
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ChannelNotConfigured(
                "Outbound MMS requires a publicly reachable HTTPS PUBLIC_BASE_URL."
            )
        identifier, token = uuid4(), secrets.token_hex(32)
        extension = mimetypes.guess_extension(file.mime_type) or ".bin"
        # Carriers require ASCII names of at most 20 characters. Preserve the
        # useful stem without handing HTTP headers a workspace-supplied path.
        stem = file.filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem) or "file"
        filename = stem[: 20 - len(extension)] + extension
        stored = StoredSmsMedia(
            filename=filename,
            mime_type=file.mime_type,
            content=base64.b64encode(file.content),
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        await self.redis.set(_key(identifier), stored.model_dump_json(), ttl=TTL_SECONDS)
        return f"{base}{settings.API_V1_STR}/sms/media/{identifier}?token={token}"

    async def open(self, media_id: UUID, token: str | None) -> StoredSmsMedia:
        """One credential opens one staged file; missing/expired/forged all give 404."""
        if token is None or _TOKEN.fullmatch(token) is None:
            raise NotFoundError(message="MMS file not found")
        raw = await self.redis.get(_key(media_id))
        if raw is None:
            raise NotFoundError(message="MMS file not found")
        stored = StoredSmsMedia.model_validate_json(raw)
        if not secrets.compare_digest(
            stored.token_hash, hashlib.sha256(token.encode()).hexdigest()
        ):
            raise NotFoundError(message="MMS file not found")
        return stored


@asynccontextmanager
async def open_media_store() -> AsyncGenerator[SmsMediaService]:
    """A sender owns its Redis connection, in both the API and background worker."""
    redis = RedisClient()
    try:
        await redis.connect()
        yield SmsMediaService(redis)
    finally:
        await redis.close()
