"""The ids that tie a mail to its thread - one parser for both mailbox pollers.

Gmail and Outlook both hand back the raw `Message-ID`, `In-Reply-To` and
`References` headers, and a reply from an external sender can only be threaded by
them (Outlook's `conversationId` is not RFC threading). Reading them in one place
keeps the two pollers from drifting apart on folding, comments and duplicates.

The archive keys a conversation on the provider's own `thread_id` and treats
`References` as a hint: a sender writes every one of these headers, so they say
what the sender claims, not what the mailbox filed together.
"""

import re
from collections.abc import Iterable
from typing import TypedDict

MAX_REFERENCES = 20
MAX_ID_CHARS = 998

# Folding (`\r\n `) and comments sit between ids and never inside one.
_ID = re.compile(r"<[^<>\s]+>")


class ThreadHeaders(TypedDict):
    """The payload keys of the same names, both pollers."""

    rfc_message_id: str  # first `<id>` in `Message-ID`, or `""`
    in_reply_to: str  # first `<id>` in `In-Reply-To`, or `""`
    references: list[str]  # ids in `References`, deduplicated, at most `MAX_REFERENCES`


def _ids(headers: Iterable[tuple[str, str]], wanted: str) -> list[str]:
    """The ids of the topmost `wanted` header, in order; an overlong one is dropped.

    The topmost occurrence wins, so a duplicated header reads one deterministic
    way. The sender writes all three headers; no server vouches for them.
    """
    value = next((value for name, value in headers if name.casefold() == wanted), "")
    return [found for found in _ID.findall(value) if len(found) <= MAX_ID_CHARS]


def thread_headers(headers: Iterable[tuple[str, str]]) -> ThreadHeaders:
    """Read the thread headers off `(name, value)` pairs in the message's order.

    `References` is deduplicated in order. Past `MAX_REFERENCES` it keeps the
    first id, the thread's root, and the most recent ones.
    """
    pairs = list(headers)
    references = list(dict.fromkeys(_ids(pairs, "references")))
    if len(references) > MAX_REFERENCES:
        references = [references[0], *references[1 - MAX_REFERENCES :]]
    message_id = _ids(pairs, "message-id")
    in_reply_to = _ids(pairs, "in-reply-to")
    return {
        "rfc_message_id": message_id[0] if message_id else "",
        "in_reply_to": in_reply_to[0] if in_reply_to else "",
        "references": references,
    }


def clean_text(value: object) -> str:
    """Text from a message as a JSONB column can store it.

    A sender controls the bytes, and JSONB refuses NUL and a lone surrogate: left in,
    the same message would fail every poll. NUL is dropped, a lone surrogate becomes U+FFFD.
    """
    text = "" if value is None else str(value)
    return text.replace("\x00", "").encode("utf-16", "surrogatepass").decode("utf-16", "replace")
