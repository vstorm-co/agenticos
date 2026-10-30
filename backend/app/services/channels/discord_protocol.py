"""What the Discord adapter says and reads, without the I/O (#2079).

Discord's API v10 spoken directly: the Gateway's identify and close codes, the
2,000-character message, buttons and selects, and the permission arithmetic
that says whether somebody can see a channel. Kept apart from
:mod:`app.services.channels.discord` so every rule is tested without a socket.
"""

import re
from collections import OrderedDict
from typing import Any

from app.services.channels.base import CHANNEL_COMMANDS, ChannelChoice
from app.services.file_storage import IMAGE_MIME_TYPES, canonical_mime

API_BASE = "https://discord.com/api/v10"
GATEWAY_QUERY = "?v=10&encoding=json"

# Gateway intents. MESSAGE_CONTENT is privileged: without it switched on in the
# Developer Portal a guild message arrives with empty text, and identifying with
# it then closes the socket with 4014.
GUILDS = 1 << 0
GUILD_MESSAGES = 1 << 9
DIRECT_MESSAGES = 1 << 12
MESSAGE_CONTENT = 1 << 15
INTENTS = GUILDS | GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT

MESSAGE_LIMIT = 2000
THREAD_NAME_LIMIT = 100
BUTTON_LABEL_LIMIT = 80
OPTION_LABEL_LIMIT = 100
BUTTONS_PER_ROW = 5
ROWS_PER_MESSAGE = 5
OPTIONS_PER_SELECT = 25

NO_MENTIONS: dict[str, list[str]] = {"parse": []}
"""`allowed_mentions` on everything the bot posts.

An answer is model output, and model output can contain `@everyone` or a
role's `<@&id>`; Discord would ping all of them. Nothing the agent writes may
notify anybody.
"""

# Channel types (https://discord.com/developers/docs/resources/channel).
DM = 1
PRIVATE_THREAD = 12
THREAD_TYPES = frozenset({10, 11, PRIVATE_THREAD})

VIEW_CHANNEL = 1 << 10
ADMINISTRATOR = 1 << 3

_UNRECOVERABLE: dict[int, str] = {
    4004: "Discord rejected the bot token. Copy a fresh one from the Developer Portal.",
    4010: "Discord refused the shard this bot identified with.",
    4011: "This bot is in too many servers for one connection; it needs sharding.",
    4012: "Discord refused the Gateway version this deployment speaks.",
    4013: "Discord refused the intents this bot asked for.",
    4014: (
        "Discord refused the Message Content intent. Switch on 'Message Content Intent' "
        "under Bot in the Developer Portal."
    ),
}

_SESSION_LOST = frozenset({4007, 4009})

_MENTION = re.compile(r"<@[!&]?\d+>")


def identify(token: str) -> dict[str, Any]:
    """The Gateway's opcode 2: who this connection is and what it wants to hear."""
    return {
        "op": 2,
        "d": {
            "token": token,
            "intents": INTENTS,
            "properties": {"os": "linux", "browser": "agenticos", "device": "agenticos"},
        },
    }


def resume(token: str, session_id: str, seq: int | None) -> dict[str, Any]:
    """The Gateway's opcode 6: pick a dropped session up where it stopped."""
    return {"op": 6, "d": {"token": token, "session_id": session_id, "seq": seq}}


def close_refusal(code: int | None) -> str | None:
    """What an operator has to fix when the Gateway closed with `code`, or `None`.

    `None` for a close a reconnect recovers from, which is most of them.
    """
    return None if code is None else _UNRECOVERABLE.get(code)


def session_lost(code: int | None) -> bool:
    """Whether a close leaves nothing to resume, so the next connection identifies afresh."""
    return code in _SESSION_LOST


ASK = "ask"
ASK_ABOUT = "Ask the agent"
"""The message command: right-click a message, then Apps."""


def commands() -> list[dict[str, Any]]:
    """The application commands a bot registers: `/ask`, the channel commands, and one on messages.

    `/start` is Telegram's greeting and has no meaning in a server, so it is left out.
    """
    return [
        {
            "name": ASK,
            "type": 1,
            "description": "Ask the agent a question",
            "options": [
                {"type": 3, "name": "question", "description": "What to ask", "required": True}
            ],
        },
        *(
            {"name": name, "type": 1, "description": what}
            for name, what in CHANNEL_COMMANDS
            if name != "start"
        ),
        {"name": ASK_ABOUT, "type": 3},
    ]


COMMENT_PREFIX = "aosfc:"
"""What the "what was wrong?" form's id starts with; the rest is the run it is about."""

_COMMENT_FIELD = "comment"


def comment_form(run_id: str) -> dict[str, Any]:
    """The interaction response that opens the "what was wrong?" form (#2084).

    A form can only be the *first* response to a press, so a thumbs-down opens it
    straight away rather than after the rating is stored.
    """
    return {
        "type": 9,
        "data": {
            "custom_id": f"{COMMENT_PREFIX}{run_id}",
            "title": "What was wrong?",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 4,
                            "custom_id": _COMMENT_FIELD,
                            "label": "Tell the agent's builders",
                            "style": 2,
                            "max_length": 2000,
                            "required": True,
                        }
                    ],
                }
            ],
        },
    }


def read_comment(data: dict[str, Any]) -> tuple[str, str] | None:
    """The run and the text a submitted form carries, or `None` for any other form."""
    custom_id = data.get("custom_id") or ""
    if not custom_id.startswith(COMMENT_PREFIX):
        return None
    text = ""
    for row in data.get("components") or []:
        for field in row.get("components") or []:
            if field.get("custom_id") == _COMMENT_FIELD:
                text = (field.get("value") or "").strip()
    run_id = custom_id.removeprefix(COMMENT_PREFIX)
    return (run_id, text) if run_id and text else None


def interaction_user(interaction: dict[str, Any]) -> dict[str, Any]:
    """Who acted: a server's interaction names a member, a direct message's a user."""
    return (interaction.get("member") or {}).get("user") or interaction.get("user") or {}


def chunks(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """`text` cut into messages Discord accepts, at a line or a word where it can.

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


def thread_name(text: str) -> str:
    """A thread's title from the message it is opened on: its first line, mentions out."""
    first = next((line for line in _MENTION.sub(" ", text).splitlines() if line.strip()), "")
    name = " ".join(first.split()).lstrip("> ").strip()
    if not name:
        return "Conversation"
    if len(name) <= THREAD_NAME_LIMIT:
        return name
    return name[: THREAD_NAME_LIMIT - 1].rstrip() + "…"


def without_mention(text: str, user_id: str) -> str:
    """The message with the bot's own mention taken out - it is the envelope, not the question.

    Only the mention and the spaces beside it: line breaks, indentation and a
    code block in the question reach the agent as they were written.
    """
    return re.sub(rf"[ \t]*<@!?{re.escape(user_id)}>[ \t]*", " ", text).strip()


def attachment_type(content_type: str | None, filename: str) -> str:
    """The MIME type an attachment is checked and stored under.

    Discord's own `content_type`, except when it names one image format and the
    file's name another: an image pasted from the clipboard arrives as
    `image.png` with PNG bytes and `image/webp` on it. Upload validation refuses
    a type that contradicts the extension, so the picture never reached the
    agent. The name's type is taken instead; the byte check after the download
    still refuses a file whose header is neither.
    """
    claimed = content_type or "application/octet-stream"
    named = canonical_mime(None, filename)
    if claimed.split(";", 1)[0].strip().lower() in IMAGE_MIME_TYPES and named in IMAGE_MIME_TYPES:
        return named
    return claimed


def _clip(label: str, limit: int) -> str:
    return label if len(label) <= limit else label[: limit - 1] + "…"


def components(choices: list[ChannelChoice]) -> list[dict[str, Any]]:
    """The action rows for a prompt: a button a choice, or selects past what buttons hold.

    Twenty-five buttons fit a message, five to a row. A question with more
    choices than that becomes string selects of twenty-five options each, as
    many as five rows allow; a choice past those cannot be offered here, and the
    console still can.
    """
    if len(choices) <= BUTTONS_PER_ROW * ROWS_PER_MESSAGE:
        return [
            {"type": 1, "components": [_button(choice) for choice in row]}
            for row in _rows(choices, BUTTONS_PER_ROW)
        ]
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 3,
                    "custom_id": f"aossel:{index}",
                    "placeholder": "Choose…",
                    "options": [
                        {"label": _clip(choice.label, OPTION_LABEL_LIMIT), "value": choice.value}
                        for choice in row
                    ],
                }
            ],
        }
        for index, row in enumerate(_rows(choices, OPTIONS_PER_SELECT)[:ROWS_PER_MESSAGE])
    ]


def _rows(choices: list[ChannelChoice], size: int) -> list[list[ChannelChoice]]:
    return [choices[start : start + size] for start in range(0, len(choices), size)]


def _button(choice: ChannelChoice) -> dict[str, Any]:
    style = {"primary": 1, "danger": 4}.get(choice.style or "", 2)
    return {
        "type": 2,
        "style": style,
        "label": _clip(choice.label, BUTTON_LABEL_LIMIT),
        "custom_id": choice.value,
    }


def pressed_value(data: dict[str, Any]) -> str | None:
    """The value a component interaction carries: a button's id, or a select's choice."""
    values = data.get("values")
    if data.get("component_type") == 3:
        return values[0] if isinstance(values, list) and values else None
    value = data.get("custom_id")
    return value if isinstance(value, str) else None


def can_view(
    *,
    user_id: str,
    guild_id: str,
    owner_id: str,
    roles: dict[str, int],
    member_roles: list[str],
    overwrites: list[dict[str, Any]],
) -> bool:
    """Whether a member can see a channel, by Discord's own permission arithmetic.

    `roles` is every role of the guild, by id, with its permission bits; the
    `@everyone` role's id is the guild's. The order of application is
    Discord's: the base from roles, then the channel's overwrites for
    `@everyone`, for the member's roles together, and for the member alone.
    """
    if user_id == owner_id:
        return True
    permissions = roles.get(guild_id, 0)
    for role in member_roles:
        permissions |= roles.get(role, 0)
    if permissions & ADMINISTRATOR:
        return True
    by_id = {str(item.get("id")): item for item in overwrites}
    everyone = by_id.get(guild_id)
    if everyone is not None:
        permissions = (permissions & ~int(everyone.get("deny", 0))) | int(everyone.get("allow", 0))
    allow = deny = 0
    for role in member_roles:
        overwrite = by_id.get(role)
        if overwrite is not None and overwrite.get("type") == 0:
            allow |= int(overwrite.get("allow", 0))
            deny |= int(overwrite.get("deny", 0))
    permissions = (permissions & ~deny) | allow
    own = by_id.get(user_id)
    if own is not None and own.get("type") == 1:
        permissions = (permissions & ~int(own.get("deny", 0))) | int(own.get("allow", 0))
    return bool(permissions & VIEW_CHANNEL)


class Recent[V]:
    """A mapping that forgets its oldest entry past `size`, for per-process caches.

    The adapter remembers which threads exist and which channels are which; a
    process up for months must not keep every id it ever saw.
    """

    def __init__(self, size: int) -> None:
        self._size = size
        self._items: OrderedDict[str, V] = OrderedDict()

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def get(self, key: str) -> V | None:
        return self._items.get(key)

    def put(self, key: str, value: V) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._size:
            self._items.popitem(last=False)
