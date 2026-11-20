"""What the Matrix adapter says and reads, without the I/O (#2081).

The Client-Server API spoken directly: the `/sync` filter, the content of a
threaded message, an edit and a reaction, the mention rules and the
authenticated media paths. Kept apart from :mod:`app.services.channels.matrix`
so every rule is tested without a homeserver.

**Room ids carry a colon.** `!abc:example.org` is the room `split_thread` would
cut in two, so the chat id this module hands the router percent-encodes it
(`room_key`) and every adapter call decodes it back (`room_of`). Rooms from room
version 12 on have ids without a server part; older rooms are still everywhere.
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

import httpx
from markdown_it import MarkdownIt

from app.services.channels.attachments import routed_type
from app.services.channels.base import IncomingAttachment, mentionable_text

CLIENT_API = "/_matrix/client/v3"
RELATIONS_API = "/_matrix/client/v1"
"""`/relations` was added under `v1` and was never given a `v3` path; a homeserver
answers 404 there."""
MEDIA_DOWNLOAD = "/_matrix/client/v1/media/download"
MEDIA_UPLOAD = "/_matrix/media/v3/upload"

MESSAGE_LIMIT = 4000
"""Characters per message, well under the 65,536-byte event limit.

An edit carries the text three times - the fallback `body`, and the body and HTML
of `m.new_content` - and a character can take four bytes, so 4,000 characters
stays inside one event with room for the JSON around it. A longer answer is
split into several messages, as on Discord."""

SYNC_TIMEOUT_MS = 30_000
"""How long one `/sync` long-poll waits for something to happen."""

SYNC_FILTER = json.dumps(
    {
        "presence": {"not_types": ["*"]},
        "account_data": {"not_types": ["*"]},
        "room": {
            "account_data": {"not_types": ["*"]},
            "ephemeral": {"not_types": ["*"]},
            "state": {"types": ["m.room.member"], "lazy_load_members": True},
            "timeline": {"types": ["m.room.message", "m.room.member"], "limit": 50},
        },
    },
    separators=(",", ":"),
)
"""Messages and membership only: typing, receipts and presence are never read."""

ATTACHMENT_TYPES = frozenset({"m.image", "m.file", "m.audio", "m.video"})
TEXT_TYPES = frozenset({"m.text", "m.emote"})

NO_MENTIONS: dict[str, Any] = {}
"""`m.mentions` on everything the bot posts: what it posts is model output, and
nothing in it may notify anybody (MSC3952)."""

_MXC = re.compile(r"^mxc://(?P<server>[A-Za-z0-9.\-:\[\]]+)/(?P<media>[A-Za-z0-9_\-]+)$")
_PILL = 'href="https://matrix.to/#/{}"'

_MARKDOWN = (
    MarkdownIt("commonmark", {"html": False, "linkify": False})
    .enable("table")
    .enable("strikethrough")
)
"""Raw HTML off: the model's own `<tags>` are escaped, never sent as markup."""


def room_key(room_id: str) -> str:
    """The room as the router keys it: its id with the colon encoded."""
    return quote(room_id, safe="!")


def room_of(key: str) -> str:
    """The room id a `room_key` stands for.

    Raises:
        ValueError: If the key is not a room. A channel tool called with
            somebody else's id must not reach the homeserver as one.
    """
    room_id = unquote(key)
    if not room_id.startswith("!") or len(room_id) > 255:
        raise ValueError("A Matrix room id is required")
    return room_id


def chunks(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """`text` cut into messages of at most `limit` characters, at a line or word.

    Always at least one piece: an empty answer is one empty message, which the
    caller decides what to do with.
    """
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = window.rfind("\n", limit // 2)
        if cut == -1:
            cut = window.rfind(" ", limit // 2)
        if cut == -1:
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip("\n ")
    pieces.append(rest)
    return pieces


def html(text: str) -> str:
    """Markdown rendered as the HTML subset Matrix clients draw."""
    return _MARKDOWN.render(text).strip()


def _thread(root: str) -> dict[str, Any]:
    """A relation into the thread rooted at `root`, with a reply fallback.

    The fallback makes a client without threads show the message as a reply to
    the root, so the answer still sits under its question.
    """
    return {
        "rel_type": "m.thread",
        "event_id": root,
        "is_falling_back": True,
        "m.in_reply_to": {"event_id": root},
    }


def text_content(text: str, *, root: str | None) -> dict[str, Any]:
    """A message, in the thread rooted at `root` when there is one."""
    content: dict[str, Any] = {
        "msgtype": "m.text",
        "body": text,
        "format": "org.matrix.custom.html",
        "formatted_body": html(text),
        "m.mentions": NO_MENTIONS,
    }
    if root:
        content["m.relates_to"] = _thread(root)
    return content


def edit_content(text: str, *, target: str) -> dict[str, Any]:
    """Replace what `target` says with `text`.

    The outer `body` is the fallback for a client without edits; it carries no
    HTML so that the event stays inside `MESSAGE_LIMIT`'s arithmetic. An edit
    takes no thread relation of its own - it belongs to its target's thread.
    """
    return {
        "msgtype": "m.text",
        "body": f"* {text}",
        "m.new_content": {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": html(text),
            "m.mentions": NO_MENTIONS,
        },
        "m.mentions": NO_MENTIONS,
        "m.relates_to": {"rel_type": "m.replace", "event_id": target},
    }


def file_content(
    filename: str, mime_type: str, size: int, uri: str, *, root: str | None
) -> dict[str, Any]:
    """A file already uploaded to `uri`, shown inline when it is an image."""
    content: dict[str, Any] = {
        "msgtype": "m.image" if mime_type.startswith("image/") else "m.file",
        "body": filename,
        "filename": filename,
        "url": uri,
        "info": {"mimetype": mime_type, "size": size},
        "m.mentions": NO_MENTIONS,
    }
    if root:
        content["m.relates_to"] = _thread(root)
    return content


def reaction_content(event_id: str, key: str) -> dict[str, Any]:
    """An emoji reaction to one message."""
    return {"m.relates_to": {"rel_type": "m.annotation", "event_id": event_id, "key": key}}


def media_url(base_url: str, uri: str) -> str:
    """Where an `mxc://` file is downloaded, over authenticated media (MSC3916).

    The unauthenticated `/_matrix/media/v3/download` is frozen on current
    homeservers, so a file is always fetched with the bot's token.

    Raises:
        ValueError: If `uri` is not a content URI.
    """
    found = _MXC.match(uri)
    if found is None:
        raise ValueError("A Matrix content URI is required")
    return f"{base_url}{MEDIA_DOWNLOAD}/{found['server']}/{found['media']}"


@dataclass(frozen=True)
class Message:
    """What the adapter reads off one `m.room.message` event."""

    event_id: str
    sender: str
    text: str
    thread_root: str | None
    mentioned: frozenset[str] | None
    """The users `m.mentions` names, or `None` where the sender's client sent none."""
    room_mentioned: bool
    formatted: str
    attachment: tuple[str, str, int, str, float | None] | None
    """Name, MIME type, claimed size, content URI and duration in seconds."""
    origin_server_ts: int | None


def read_message(event: dict[str, Any]) -> Message | None:
    """The message an event carries, or `None` for one the bot never answers.

    Not answered: an edit (the original was already read), a notice - the
    message type bots post, so two bots do not answer each other for ever - a
    redacted message, and an encrypted file, which needs the keys of the second
    stage (#2081).
    """
    if event.get("type") != "m.room.message":
        return None
    content = event.get("content")
    event_id, sender = event.get("event_id"), event.get("sender")
    if (
        not isinstance(content, dict)
        or not isinstance(event_id, str)
        or not isinstance(sender, str)
    ):
        return None
    relation = content.get("m.relates_to")
    relation = relation if isinstance(relation, dict) else {}
    if relation.get("rel_type") == "m.replace":
        return None
    msgtype = content.get("msgtype")
    body = content.get("body")
    if not isinstance(body, str) or msgtype not in TEXT_TYPES | ATTACHMENT_TYPES:
        return None
    attachment = None
    if msgtype in ATTACHMENT_TYPES:
        uri = content.get("url")
        if not isinstance(uri, str) or _MXC.match(uri) is None:
            return None
        info = content.get("info") if isinstance(content.get("info"), dict) else {}
        name = content.get("filename") if isinstance(content.get("filename"), str) else body
        size = info.get("size", 0)
        duration = info.get("duration")
        # Event content is chosen by the sender, not validated by the homeserver.
        # Ignore a malformed file without poisoning the bot's sync position.
        if type(size) is not int or size < 0:
            return None
        attachment = (
            name or "attachment",
            str(info.get("mimetype") or ""),
            size,
            uri,
            duration / 1000 if isinstance(duration, int | float) else None,
        )
        body = ""
    thread_root = relation.get("event_id") if relation.get("rel_type") == "m.thread" else None
    if not isinstance(thread_root, str):
        thread_root = None
    if "m.in_reply_to" in relation and not relation.get("is_falling_back"):
        # A real reply, not a thread's fallback: older clients quote the replied-to
        # message above the text, and the agent must not read it as the question.
        body = without_reply_fallback(body)
    mentions = content.get("m.mentions")
    mentioned: frozenset[str] | None = None
    room_mentioned = False
    if isinstance(mentions, dict):
        users = mentions.get("user_ids")
        mentioned = (
            frozenset(user for user in users if isinstance(user, str))
            if isinstance(users, list)
            else frozenset()
        )
        room_mentioned = mentions.get("room") is True
    formatted = content.get("formatted_body")
    timestamp = event.get("origin_server_ts")
    return Message(
        event_id=event_id,
        sender=sender,
        text=f"* {body}" if msgtype == "m.emote" and body else body,
        thread_root=thread_root,
        mentioned=mentioned,
        room_mentioned=room_mentioned,
        formatted=formatted if isinstance(formatted, str) else "",
        attachment=attachment,
        origin_server_ts=timestamp if isinstance(timestamp, int) else None,
    )


def with_latest_edit(event: dict[str, Any]) -> dict[str, Any]:
    """The event as it reads now, with the edit the homeserver bundled applied.

    Every answer the bot streams is a placeholder edited into place, so a history
    read without its edits is a thread of "…". The thread relation stays the
    original's: an edit's `m.new_content` carries none.
    """
    unsigned = event.get("unsigned")
    relations = unsigned.get("m.relations") if isinstance(unsigned, dict) else None
    edit = relations.get("m.replace") if isinstance(relations, dict) else None
    content = edit.get("content") if isinstance(edit, dict) else None
    new = content.get("m.new_content") if isinstance(content, dict) else None
    original = event.get("content")
    if not isinstance(new, dict) or not isinstance(original, dict):
        return event
    return {**event, "content": {**original, **new}}


def without_reply_fallback(body: str) -> str:
    """The body with the `> quoted` reply fallback older clients prepend taken off."""
    lines = body.split("\n")
    if not lines or not lines[0].startswith("> "):
        return body
    index = 0
    while index < len(lines) and lines[index].startswith(">"):
        index += 1
    return "\n".join(lines[index:]).lstrip("\n")


def _handles(user_id: str, display_name: str | None) -> list[str]:
    """What a person may type after `@` to name the bot: its user id, localpart and display name."""
    localpart = user_id.removeprefix("@").partition(":")[0]
    return [handle for handle in (user_id.removeprefix("@"), localpart, display_name) if handle]


def _handle_pattern(handle: str) -> str:
    # Not inside a word or an address (`agent@example.org`), and not a longer
    # handle (`@agent-ops`): the characters a localpart may continue with end it.
    return rf"(?<![\w@])@{re.escape(handle)}(?![\w.=/+-])"


def names(message: Message, user_id: str, display_name: str | None) -> bool:
    """Whether the message addresses `user_id`.

    `m.mentions` naming the bot, a pill linking to it, or a typed handle: `@`
    and its user id, localpart or display name. The handle counts because some
    clients send a typed `@name` as plain text with an empty `m.mentions`, and a
    bot that only answers pills looks broken to everybody using one (#2081). It
    is read as the router reads a typed `@agent-slug`: an explicit handle outside
    code, never a bare word - a bot called Agent must not answer "agent".
    """
    if message.mentioned is not None and user_id in message.mentioned:
        return True
    if _PILL.format(user_id) in message.formatted:
        return True
    text = mentionable_text(message.text)
    return any(
        re.search(_handle_pattern(handle), text, re.I) for handle in _handles(user_id, display_name)
    )


def without_mention(text: str, user_id: str, display_name: str | None) -> str:
    """The text with the bot's own mention taken out.

    A pill arrives in the plain body as the bot's display name, often followed by
    a colon, and a typed handle as `@name`; the agent is the addressee, and its
    own name handed to it as content reads as part of the question. A bare
    display name is removed only at the start: the same word mid-sentence may be
    meant. Only spaces and tabs beside a mention go with it, so line breaks and
    code blocks reach the agent as written.
    """
    stripped = text
    for handle in sorted(_handles(user_id, display_name), key=len, reverse=True):
        stripped = re.sub(rf"[ \t]*{_handle_pattern(handle)}:?[ \t]*", " ", stripped, flags=re.I)
    if display_name:
        stripped = re.sub(
            rf"^[ \t]*{re.escape(display_name)}[ \t]*[:,]?[ \t]*", "", stripped, count=1, flags=re.I
        )
    return stripped.strip()


def attachment_of(message: Message, base_url: str) -> IncomingAttachment | None:
    """The file a message carries, as a handle on the bot's own homeserver."""
    if message.attachment is None:
        return None
    name, mime_type, size, uri, duration = message.attachment
    return IncomingAttachment(
        filename=name,
        mime_type=routed_type(mime_type or None, name),
        size=size,
        handle=media_url(base_url, uri),
        duration_seconds=duration,
        author_id=message.sender,
    )


def display_names(events: list[dict[str, Any]]) -> dict[str, str]:
    """Who is called what, from the `m.room.member` events of a sync.

    A sync with lazy-loaded members carries the membership of every sender in
    its timeline, so the sender of a message is named in the same batch.
    """
    names_found: dict[str, str] = {}
    for event in events:
        content = event.get("content")
        user, name = (
            event.get("state_key"),
            content.get("displayname") if isinstance(content, dict) else None,
        )
        if event.get("type") == "m.room.member" and isinstance(user, str) and isinstance(name, str):
            names_found[user] = name
    return names_found


def encrypted_invitation(events: list[dict[str, Any]]) -> bool:
    """Whether an invitation's stripped state says the room is end-to-end encrypted.

    `m.room.encryption` is among the state a homeserver shows an invited user,
    so the bot can tell before joining that it would read nothing there.
    """
    return any(event.get("type") == "m.room.encryption" for event in events)


def error_code(response: httpx.Response) -> str | None:
    """The `errcode` a homeserver's error body names, or `None`."""
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("errcode") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def retry_after(response: httpx.Response, *, default: float = 1.0) -> float:
    """Seconds a 429 asks to wait: `retry_after_ms` in the body, else `Retry-After`."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    milliseconds = body.get("retry_after_ms") if isinstance(body, dict) else None
    if isinstance(milliseconds, int | float) and milliseconds >= 0:
        return milliseconds / 1000
    header = response.headers.get("retry-after", "")
    return float(header) if header.isdecimal() else default
