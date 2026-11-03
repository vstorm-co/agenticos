"""WhatsApp webhook payloads: the signature, and what Meta sent, read defensively (#2076).

Pure functions, no I/O. Meta posts batches - several customers, several kinds, plus
delivery statuses - and an unparsable corner of one must never lose the rest, so
parsing counts what it drops instead of raising.
"""

import hashlib
import hmac
import mimetypes
import secrets
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.services.channels.base import IncomingAttachment, IncomingMessage

MAX_MESSAGE_AGE = timedelta(days=7)
"""Meta retries a refused webhook for up to a week; older than that is not a live conversation."""

IGNORED_KINDS = frozenset({"reaction", "system"})
"""A reaction asks for no answer; a `system` number-change event is logged only, because
the new id arrives as a new customer."""

_MEDIA_KINDS = frozenset({"image", "document", "audio", "video"})


def verify_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    """Whether `X-Hub-Signature-256` is the HMAC-SHA256 of the raw body under the app secret."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return secrets.compare_digest(header.removeprefix("sha256=").encode(), expected.encode())


@dataclass(frozen=True)
class WhatsAppMessage:
    wamid: str
    bsuid: str
    kind: str
    text: str
    sent_at: datetime
    profile_name: str | None
    username: str | None
    phone: str | None = field(repr=False)
    media_id: str | None
    mime_type: str | None
    filename: str | None


@dataclass(frozen=True)
class WhatsAppStatus:
    wamid: str
    status: str
    error_codes: tuple[int, ...]


@dataclass(frozen=True)
class ParsedWebhook:
    """What one webhook body held for one bot.

    `foreign` counts whole changes (another number or account); `stale`,
    `unidentified` and `ignored` count messages.
    """

    messages: tuple[WhatsAppMessage, ...]
    statuses: tuple[WhatsAppStatus, ...]
    foreign: int
    stale: int
    unidentified: int
    ignored: int


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _location_text(location: Mapping[str, Any]) -> str:
    place = ", ".join(p for p in (_str(location.get("name")), _str(location.get("address"))) if p)
    latitude, longitude = location.get("latitude"), location.get("longitude")
    coordinates = (
        f"({latitude}, {longitude})"
        if isinstance(latitude, int | float) and isinstance(longitude, int | float)
        else ""
    )
    return " ".join(part for part in ("Location:", place, coordinates) if part)


def _message(raw: object, contacts: Mapping[str, Mapping[str, Any]]) -> WhatsAppMessage | None:
    """One message, or `None` when a required field is missing or malformed."""
    item = _mapping(raw)
    wamid, kind = _str(item.get("id")), _str(item.get("type"))
    bsuid = _str(item.get("from_user_id")) or _str(item.get("user_id"))
    timestamp = item.get("timestamp")
    if not (wamid and kind and bsuid and isinstance(timestamp, str | int)):
        return None
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), UTC)
    except ValueError, OverflowError, OSError:
        return None

    text, media_id, mime_type, filename = "", None, None, None
    if kind == "text":
        body = _mapping(item.get("text")).get("body")
        if not isinstance(body, str):
            return None
        text = body
    elif kind == "location":
        text = _location_text(_mapping(item.get("location")))
    elif kind in _MEDIA_KINDS:
        media = _mapping(item.get(kind))
        text = _str(media.get("caption")) or ""
        media_id = _str(media.get("id"))
        if media_id is None:
            return None
        mime_type = _str(media.get("mime_type"))
        filename = _str(media.get("filename"))

    contact = contacts.get(bsuid, {})
    profile = _mapping(contact.get("profile"))
    return WhatsAppMessage(
        wamid=wamid,
        bsuid=bsuid,
        kind=kind,
        text=text,
        sent_at=sent_at,
        profile_name=_str(profile.get("name")),
        username=_str(profile.get("username")),
        phone=_str(item.get("from")) or _str(contact.get("wa_id")),
        media_id=media_id,
        mime_type=mime_type,
        filename=filename,
    )


def _status(raw: object) -> WhatsAppStatus | None:
    item = _mapping(raw)
    wamid, status = _str(item.get("id")), _str(item.get("status"))
    if not (wamid and status):
        return None
    errors = item.get("errors")
    codes = tuple(
        code
        for error in (errors if isinstance(errors, list) else [])
        if isinstance(code := _mapping(error).get("code"), int)
    )
    return WhatsAppStatus(wamid=wamid, status=status, error_codes=codes)


def parse_webhook(
    payload: Mapping[str, Any], *, phone_number_id: str, account_id: str, now: datetime
) -> ParsedWebhook:
    """Read a webhook body for one bot; never raises.

    Only `messages` changes are read. A change for another number or account is
    `foreign` (one app can serve several numbers); a message older than
    `MAX_MESSAGE_AGE` is `stale`; one with no business-scoped user id, or with a
    malformed required field, is `unidentified` - never guessed at.
    """
    messages: list[WhatsAppMessage] = []
    statuses: list[WhatsAppStatus] = []
    foreign = stale = unidentified = ignored = 0
    entries = payload.get("entry")
    for entry in entries if isinstance(entries, list) else []:
        changes = _mapping(entry).get("changes")
        for change in changes if isinstance(changes, list) else []:
            if _mapping(change).get("field") != "messages":
                continue
            value = _mapping(_mapping(change).get("value"))
            if (
                _mapping(entry).get("id") != account_id
                or _mapping(value.get("metadata")).get("phone_number_id") != phone_number_id
            ):
                foreign += 1
                continue
            raw_contacts = value.get("contacts")
            contacts = {
                uid: _mapping(contact)
                for contact in (raw_contacts if isinstance(raw_contacts, list) else [])
                if (uid := _str(_mapping(contact).get("user_id")))
            }
            raw_messages = value.get("messages")
            for raw in raw_messages if isinstance(raw_messages, list) else []:
                if _str(_mapping(raw).get("type")) in IGNORED_KINDS:
                    ignored += 1
                    continue
                parsed = _message(raw, contacts)
                if parsed is None:
                    unidentified += 1
                elif now - parsed.sent_at > MAX_MESSAGE_AGE:
                    stale += 1
                else:
                    messages.append(parsed)
            raw_statuses = value.get("statuses")
            for raw in raw_statuses if isinstance(raw_statuses, list) else []:
                if (status := _status(raw)) is not None:
                    statuses.append(status)
    messages.sort(key=lambda message: message.sent_at)
    return ParsedWebhook(
        messages=tuple(messages),
        statuses=tuple(statuses),
        foreign=foreign,
        stale=stale,
        unidentified=unidentified,
        ignored=ignored,
    )


def group_by_customer(messages: Sequence[WhatsAppMessage]) -> list[list[WhatsAppMessage]]:
    """Messages per customer: customers in first-seen order, each customer's in `sent_at` order."""
    groups: dict[str, list[WhatsAppMessage]] = defaultdict(list)
    for message in messages:
        groups[message.bsuid].append(message)
    return [sorted(group, key=lambda message: message.sent_at) for group in groups.values()]


def platform_user_id_for(organization_id: UUID, bsuid: str) -> str:
    """A business-scoped id is unique per business portfolio, so namespace it by organization."""
    return f"{organization_id}:{bsuid}"


def mask_phone(phone: str | None) -> str | None:
    """`•••• 1234`, or `None` when there are not four digits to show."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    return f"•••• {digits[-4:]}" if len(digits) >= 4 else None


def _attachment(message: WhatsAppMessage) -> IncomingAttachment | None:
    if message.kind in _MEDIA_KINDS and message.media_id:
        # `audio/ogg; codecs=opus` is a voice note: the parameters stay out of the
        # file's name and of the type the gates compare against.
        mime_type = message.mime_type.split(";")[0].strip() if message.mime_type else None
        extension = mimetypes.guess_extension(mime_type) if mime_type else None
        return IncomingAttachment(
            filename=message.filename or f"{message.kind}{extension or ''}",
            mime_type=mime_type or "application/octet-stream",
            size=0,  # Meta states no size in the webhook; the fetch re-checks the bytes.
            handle=message.media_id,
        )
    if message.kind in {"text", "location"}:
        return None
    # Something the adapter cannot read yet still reaches the router as a named file, so
    # the access, dedupe and rate-limit gates answer it - it never vanishes.
    return IncomingAttachment(
        filename=f"{message.kind} message",
        mime_type="application/octet-stream",
        size=0,
        handle=message.wamid,
    )


def to_incoming(message: WhatsAppMessage, *, bot_id: str, organization_id: UUID) -> IncomingMessage:
    """The router's view of one message. `raw` stays empty: it would carry the phone number."""
    attachment = _attachment(message)
    return IncomingMessage(
        platform="whatsapp",
        bot_id=bot_id,
        platform_user_id=platform_user_id_for(organization_id, message.bsuid),
        platform_chat_id=message.bsuid,
        chat_type="private",
        text=message.text,
        raw={},
        platform_username=message.username or mask_phone(message.phone),
        platform_display_name=message.profile_name,
        message_id=message.wamid,
        attachments=[attachment] if attachment else [],
    )
