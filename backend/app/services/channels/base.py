from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

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
    message_id: str | None = None
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

    @abstractmethod
    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Start long-polling loop for this bot (dev mode)."""

    @abstractmethod
    async def stop_polling(self, bot_id: str) -> None:
        """Stop polling for this bot."""

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
