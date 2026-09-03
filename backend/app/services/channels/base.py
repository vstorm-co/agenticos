from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agents.capabilities.channel_tools import (
    ChannelDetails,
    ChannelDirectoryUnsupported,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
)

# Handles every chat platform reserves for addressing the room, rather than one
# member of it. They match the shape of an agent slug, so `@channel deploying at
# five` parsed as a mention of an agent called `channel` - and because a
# channel-wide mention puts every member including the bot in the platform's own
# mention list, the bot read itself as named and answered "no agent here answers
# to @channel" under every announcement. Here rather than in `mentions`, because
# `agent_registry.slugify` reads the same set and cannot import that module.
ROOM_HANDLES = frozenset({"channel", "all", "here", "everyone"})

# Surface a conversation is happening on. "web" is the chat UI / API; the
# others are messaging platforms. Extend this when adding new channels.
ChannelType = Literal["web", "slack", "telegram", "mattermost"]

# Default access policy applied to new channel bots.  Imported by models and
# repositories so the literal is defined in exactly one place.
DEFAULT_ACCESS_POLICY: dict[str, Any] = {
    "mode": "open",
    "whitelist": [],
    "allowed_groups": [],
    "require_link": False,
    "rate_limit_rpm": 10,
    "denied_message": "You are not authorised to use this bot.",
}

# When a bot says what a turn cost, and when it only records it. Here beside the
# access policy for the same reason that one is: the literal is imported by the
# model, the repository and the service, and `app/db/models/**` cannot import a
# service without a cycle.
#
# `near_limit` rather than `off`: a bot that stops answering because an
# organization hit its cap looks broken, and the difference between "broken" and
# "out of budget" is somebody having said so beforehand. Rather than `always`,
# because a footer under every reply in a busy channel is the other way to make a
# warning useless.
DEFAULT_USAGE_REPORTING: dict[str, Any] = {
    "mode": "near_limit",
    "near_limit_percent": 80,
    "every_n": 10,
}

# JSON-serialised form used by SQLite model defaults (stored as TEXT).
DEFAULT_ACCESS_POLICY_JSON: str = (
    '{"mode":"open","whitelist":[],"allowed_groups":[],'
    '"require_link":false,"rate_limit_rpm":10,'
    '"denied_message":"You are not authorised to use this bot."}'
)


def channel_key(platform_chat_id: str) -> str:
    """The chat a message arrived in, with any thread stripped.

    Slack folds `thread_ts` into `platform_chat_id` as `channel:thread_ts` and
    Mattermost folds `root_id` in the same way, so the raw id identifies a
    *thread*. Anything scoped to the channel - a workspace shared across its
    threads, an API call about the channel itself - has to key on what is stable
    across them, which is the part before the colon. Every other platform's id
    is already the chat.

    Here rather than in `mentions`, where it started: `channels.membership`
    asks the platform about the channel too and must not drag the agent runtime
    in with the import - and two implementations of "which channel is this" is
    how one of them ends up asking Mattermost about a thread id.
    """
    return split_thread(platform_chat_id)[0]


def split_thread(platform_chat_id: str) -> tuple[str, str]:
    """The chat and the thread a message's id folds together.

    Slack packs `channel:thread_ts` into `platform_chat_id` and Mattermost packs
    `channel:root_id` the same way; every other platform's id is the chat with an
    empty thread. `channel_key` keeps the channel half alone; this keeps both, for
    a reply that has to be posted back into the thread it came from. The empty
    string when there is no colon is what an unthreaded reply passes on, which each
    adapter reads as "top of the channel".
    """
    channel, _, thread = platform_chat_id.partition(":")
    return channel, thread


def thread_key(channel_id: str, *, thread_id: str, message_id: str | None) -> str:
    """The id a message's conversation is keyed on, threads included.

    **A thread is a conversation, wherever the thread is.** A message already in
    one keys on it; a message that is not yet in one keys on *itself*, because
    that is where the reply's thread will be rooted. Keyed on the bare channel
    the two would be different conversations, so the agent would answer a
    question and then, one message later in the thread it had just opened, have
    no memory of it - and every unrelated mention in that channel would pile
    into one conversation besides (#1339).

    That now holds in a **direct message** too, where the chat used to be the
    unit. One continuous conversation is the wrong default on a platform with
    threads: a DM never rolls over, so it walks past the context window in days
    and every turn pays for the whole history. Threading makes each question its
    own conversation, which is a per-topic context rather than one that has to
    be trimmed - and the cost is real and worth stating: a new message typed at
    the bottom of a DM starts fresh, so continuing means replying **inside the
    thread**. Conversations from before are not migrated; they stop being
    reached, and nothing in them is lost.

    A platform that identifies no message keys on the chat, which is what
    Telegram's ordinary chats would need - better one conversation per chat than
    one per unidentifiable turn - though Telegram has no threads and does not
    come through here at all.

    This is the only place that decides, and the adapters read the thread back
    out of the id with :func:`split_thread`. Two mechanisms - an id here and a
    `reply_to_message_id` fallback in each adapter - is what let them disagree.
    """
    if thread_id:
        return f"{channel_id}:{thread_id}"
    if not message_id:
        return channel_id
    return f"{channel_id}:{message_id}"


@dataclass(frozen=True)
class IncomingAttachment:
    """A file somebody sent a bot, before it has been fetched.

    Metadata and a **handle**, not bytes. Every platform makes the file
    available behind a second authenticated request - Slack needs its private
    download URL fetched with the bot token, Telegram needs `getFile` to turn a
    `file_id` into a path, Mattermost needs `/files/{id}` - so parsing a webhook
    cannot produce the contents, and pretending otherwise would put an HTTP call
    inside a synchronous parser.

    The handle is whatever that platform's adapter needs to fetch it, and is only
    ever read by the adapter that produced it.
    """

    filename: str
    mime_type: str
    size: int
    """What the platform claims, which is what the size check is applied to
    before anything is downloaded. Re-checked against the bytes afterwards,
    because a claim is not a measurement."""

    handle: str
    """Opaque to everything but the adapter that made it."""


@dataclass(frozen=True)
class OutgoingAttachment:
    """A file to post back, already in hand."""

    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class IncomingMessage:
    """Normalised message from any messaging platform."""

    platform: str
    bot_id: str  # UUID str of the ChannelBot row
    platform_user_id: str
    platform_chat_id: str
    chat_type: str  # "private" | "group" | "supergroup" | "channel"
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    platform_username: str | None = None
    platform_display_name: str | None = None
    one_to_one: bool = False
    """Whether this chat holds exactly this person and the bot, and nobody else.

    Deliberately not `chat_type == "private"`. Slack reports a multi-person
    direct message as `im`-like and Mattermost has group channels of the same
    shape, so `chat_type` answers "is this off-channel", which is a different
    question. This one gates speaking through a member's own MCP account, and a
    second reader in the room is exactly what must not happen - so each adapter
    sets it from the one channel kind it knows holds one person.
    """
    message_id: str | None = None
    addressed: bool | None = None
    """Whether this message named the bot, where the platform says.

    `None` means it did not say, and the two are not the same answer: a platform
    that reports mentions lets a bot sit in a busy channel and only speak when
    somebody asks it, while `None` leaves the behaviour a bot had before - answer
    whatever arrives, because what arrives is what that platform chose to deliver.

    Mattermost and Slack both set it, and both for the same reason: each can be
    handed every message in every channel the bot is in - Mattermost's socket
    always is, and a Slack app subscribed to `message.channels` is - so a default
    agent answering all of them is a bot that talks over a team it was invited
    to (agenticos#634 on Mattermost, and the same defect on Slack). Telegram
    delivers on its own subscription rules and leaves this unset.
    """

    attachments: list[IncomingAttachment] = field(default_factory=list)
    """Files sent with this message, unfetched.

    A message with attachments and no text is a real message - somebody dropping
    a spreadsheet in with nothing to say about it - so the adapters no longer
    treat empty text as nothing to do. That was the previous behaviour and it
    meant a file sent to a bot was silently dropped and the agent answered about
    a document it never received.
    """


@dataclass
class OutgoingMessage:
    """Reply to send back to the platform.

    When `image_png` is set, adapters send it as a photo/file with
    `text` used as the caption; otherwise a plain text message is sent.
    """

    platform_chat_id: str
    text: str
    parse_mode: str | None = None  # "Markdown" | "HTML" | None
    reply_to_message_id: str | None = None
    image_png: bytes | None = None
    image_filename: str = "chart.png"
    attachments: list[OutgoingAttachment] = field(default_factory=list)
    """Files to post with the reply.

    `image_png` is kept beside this rather than folded into it. A chart is not an
    attachment on any of these platforms - it is a *photo*, rendered inline, which
    is the whole reason `charts` produces one - and every adapter sends it through
    a different call. Collapsing the two would make every chart arrive as a
    downloadable file.
    """
    # Where the platform lives, for the ones that are not a single SaaS host.
    # Slack and Telegram ignore it; a Mattermost bot cannot send without it,
    # because every deployment is somebody's own server.
    api_base_url: str | None = None


class ChannelAdapter(ABC):
    """Abstract base class for all messaging platform adapters."""

    platform: str  # class-level constant e.g. "telegram"

    @abstractmethod
    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send a reply back to the platform."""

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post a message that will be rewritten as the answer arrives.

        Returns a handle to pass back to :meth:`update_reply`, or `None` when
        this platform cannot edit what it has sent. `None` is not a failure: the
        caller falls back to posting one finished message, which is what every
        adapter did before this existed.

        Not abstract for that reason - an adapter that cannot stream should not
        have to say so in a stub, and a new one is correct on the day it is
        written.
        """
        return None

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        """Rewrite the message `handle` names.

        Only ever called with a handle this adapter returned, so an adapter that
        cannot stream never reaches it.
        """
        raise NotImplementedError(f"{self.platform} cannot edit a message it has sent")

    async def typing(self, bot_id: str, msg: OutgoingMessage) -> None:  # noqa: B027
        """Show that the bot is composing, if the platform has such a thing.

        Keyed on the bot rather than the token because the platforms that offer
        this offer it over a connection the adapter already holds. Silent by
        default and never fatal: a missing typing indicator is a smaller problem
        than the answer it precedes.

        Not abstract, and deliberately a no-op rather than a raise: every caller
        would otherwise have to ask whether the platform has one, and the answer
        "it does not" is the same as "nothing happened".

        The `noqa` is that decision: B027 wants an empty method on an abstract
        base to be abstract, and making it so would force every adapter to write
        the same stub for a feature only some platforms have.
        """

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch what somebody sent, using this platform's own second request.

        Not abstract: a platform this build cannot fetch files from is better off
        saying so than forcing every adapter to implement a stub. A surface that
        never produces attachments never calls this.

        Raises:
            NotImplementedError: If this platform's adapter cannot fetch files.
                Reported to the sender rather than swallowed - a bot that ignores
                an attachment looks like a bot that read it.
        """
        raise NotImplementedError(f"{self.platform} attachments cannot be downloaded yet")

    #
    # The implementation half of `app.agents.capabilities.channel_tools`: the
    # capability declares one shape for all three platforms so an agent does not
    # have to know which one it is standing on, and each adapter answers it with
    # its own API. None of them is abstract, and every one raises by default -
    # a platform that has no equivalent says so with a sentence somebody in a
    # chat window can read, rather than every adapter writing four stubs for
    # questions its platform cannot answer.
    #
    # `api_base_url` is here for the same reason it is on `OutgoingMessage`:
    # Mattermost is self-hosted, so there is no address to assume. Slack and
    # Telegram ignore it.

    async def channel_details(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None
    ) -> ChannelDetails:
        """Name, purpose, topic and size of one channel.

        Raises:
            ChannelDirectoryUnsupported: If this platform does not tell a bot.
        """
        raise ChannelDirectoryUnsupported(f"{self.platform} cannot describe a channel to a bot.")

    async def channel_members(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, limit: int
    ) -> list[ChannelMember]:
        """Who is in one channel, up to `limit`.

        Raises:
            ChannelDirectoryUnsupported: If this platform does not tell a bot.
        """
        raise ChannelDirectoryUnsupported(f"{self.platform} cannot list a channel's members.")

    async def is_channel_member(
        self, bot_token: str, channel_id: str, platform_user_id: str, *, api_base_url: str | None
    ) -> bool:
        """Whether one platform account is currently in one channel.

        Asked per account rather than read off :meth:`channel_members`, because
        that list cannot carry the answer: on Telegram it is only the
        administrators, and on the other two it stops at `limit` - so an
        ordinary member of a large room would read as absent. This is the
        question `/chat`'s participant model puts to the platform before a
        thread is shown (#641).

        Raises:
            ChannelDirectoryUnsupported: If this platform does not tell a bot.
        """
        raise ChannelDirectoryUnsupported(
            f"{self.platform} cannot say whether an account is in a channel."
        )

    async def search_channels(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, query: str, limit: int
    ) -> list[ChannelSummary]:
        """Channels matching `query` within the bot's reach.

        `channel_id` is the channel the run is in, not one to search: on
        Mattermost it is what the team to search is resolved from, because a bot
        token has no business enumerating a whole server.

        Raises:
            ChannelDirectoryUnsupported: If this platform has no channel search.
        """
        raise ChannelDirectoryUnsupported(f"{self.platform} has no channel search for a bot.")

    async def channel_history(
        self,
        bot_token: str,
        channel_id: str,
        *,
        api_base_url: str | None,
        limit: int,
        thread_id: str | None = None,
    ) -> list[ChannelPost]:
        """The last `limit` messages in one conversation, newest last.

        `thread_id` is the conversation the agent is actually in. On a platform
        with threads the channel and the thread are different transcripts, and
        the agent answering inside a thread was being handed the *channel's* -
        so "summarise what we decided above" summarised whatever else the room
        had been saying. An adapter that supports threads reads the thread when
        it is given one; `None` is the channel, which is what a top-level
        message is in.

        Raises:
            ChannelDirectoryUnsupported: If this platform does not let a bot read
                messages it was not sent.
        """
        raise ChannelDirectoryUnsupported(
            f"{self.platform} does not let a bot read a channel's history."
        )

    async def thread_attachments(
        self,
        bot_token: str,
        channel_id: str,
        *,
        thread_id: str,
        api_base_url: str | None,
        limit: int,
    ) -> list[IncomingAttachment]:
        """Files posted in a thread before we were brought into it, as handles.

        Separate from `channel_history` rather than carried on `ChannelPost`,
        because of the layering: `ChannelPost` is the *capability's* contract and
        lives in `app/agents/capabilities/channel_tools`, which this module
        imports from - so a handle, which is transport, cannot hang off it
        without inverting that. One method here answers with the transport type
        and nothing has to move.

        Handles, not bytes, like `IncomingAttachment` everywhere else: fetching
        belongs to `ChannelAttachmentService`, which validates the size and
        stores the row.

        Raises:
            ChannelDirectoryUnsupported: If this platform has no threads, or does
                not let a bot read messages it was not sent.
        """
        raise ChannelDirectoryUnsupported(
            f"{self.platform} does not let a bot read a thread's files."
        )

    @abstractmethod
    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Start long-polling loop for this bot (dev mode)."""

    @abstractmethod
    async def stop_polling(self, bot_id: str) -> None:
        """Stop polling for this bot."""

    async def aclose(self) -> None:
        """Release long-lived resources at shutdown.

        A no-op by default; an adapter that holds a reused HTTP client (#952)
        overrides this to close it. Called once, after polling has stopped and
        background work has drained.
        """
        return

    @abstractmethod
    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """Register webhook URL with the platform. Returns True on success."""

    @abstractmethod
    async def delete_webhook(self, bot_token: str) -> bool:
        """Remove webhook from the platform."""

    @abstractmethod
    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Verify that a webhook request came from the platform.

        Args:
            headers: HTTP request headers.
            secret: The shared secret / signing key for this platform.
            body: Raw request body string. Required by platforms that sign the
                body (e.g. Slack HMAC-SHA256). Optional for platforms that use a
                header-only token (e.g. Telegram).
        """

    @abstractmethod
    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """Parse raw platform payload into IncomingMessage. Return None to ignore."""
