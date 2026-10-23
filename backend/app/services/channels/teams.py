"""Microsoft Teams, over the Bot Connector's Activity protocol (#1985).

A bot is an Azure Bot registration - an Entra app, single-tenant - and the
console hands out the Teams app package that installs it. Teams posts every
activity to `/api/v1/teams/{bot_id}/messages`; the route checks the Bot
Connector's token (`teams_auth`) before anything here reads a field.

**Where a conversation lives.** Each activity names the Connector service that
sent it (`serviceUrl`) and the conversation, and an answer goes back to the same
pair. The route records both in `teams_conversations` on every activity and
tells this adapter, which keeps them in memory for the reply and reads the table
for anything later - an answer to a run resumed from the console, a trigger's
post.

**What the channel layer calls a conversation.** A Teams id is long and full of
colons; the channel layer keys conversations on a hundred-character id and reads
a colon as "channel, then thread". So a conversation is known by
`conversation_key`, a hash of Teams' id, and a channel thread by
`<key>:<root message id>`. A personal or group chat has no threads, and is one
conversation.

**Who is speaking** is the member's Entra object id (`aadObjectId`), which is
stable across every chat in the tenant - Teams' own `29:` user id is different
for every bot.
"""

import base64
import hashlib
import html
import logging
import mimetypes
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2

from app.agents.capabilities.channel_tools import ChannelDetails, ChannelMember
from app.clients.redis import RedisClient
from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.services.channels.base import (
    ChannelAdapter,
    ChannelChoice,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
    split_thread,
    thread_key,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.teams_auth import TeamsAuth, TeamsCredentials, is_connector_url
from app.services.transcription import MAX_BYTES as TRANSCRIPTION_MAX_BYTES

logger = logging.getLogger(__name__)

MESSAGE_LIMIT_BYTES = 24_000
"""How much text one message carries. Teams refuses a message over about 28 KB,
and the envelope and any card take some of that."""

PRESS_VERB = "aos"
"""The `Action.Execute` verb on every button the bot draws."""

FILE_CONSENT_TTL_SECONDS = 15 * 60
"""How long a file waits for the person to accept it. Teams' consent card stays
in the chat for ever; the bytes behind it do not."""

FILE_CONSENT_CARD = "application/vnd.microsoft.teams.card.file.consent"
FILE_INFO_CARD = "application/vnd.microsoft.teams.card.file.info"
FILE_DOWNLOAD_INFO = "application/vnd.microsoft.teams.file.download.info"
ADAPTIVE_CARD = "application/vnd.microsoft.card.adaptive"

# Each scan stops at the next `<`, which is where the next attempt starts, so a
# message of nothing but `<` or `<at>` costs linear time, not quadratic. A
# mention's text is a display name, which holds no markup.
_AT_TAG = re.compile(r"<at[^<>]*>([^<]*)</at>", re.IGNORECASE)
_TAG = re.compile(r"<[^<>]+>")

_pending_files: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis that holds files waiting for consent.

    A file goes to a personal chat only once the person accepts it, and the
    acceptance can reach any API worker. Unconfigured - a worker process posting a
    trigger's result - files are named in the text rather than offered.
    """
    global _pending_files
    _pending_files = redis


def conversation_key(conversation_id: str) -> str:
    """The channel layer's name for a Teams conversation: 32 hex characters of its hash."""
    return hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ConversationRef:
    """Where a conversation lives: Teams' id for it, and the service that hosts it."""

    conversation_id: str
    service_url: str
    conversation_type: str
    tenant_id: str | None = None
    name: str | None = None

    @property
    def key(self) -> str:
        return conversation_key(self.conversation_id)


def conversation_of(activity: dict[str, Any]) -> ConversationRef | None:
    """The conversation an activity came from, without a channel thread's suffix."""
    conversation = activity.get("conversation") or {}
    raw_id = conversation.get("id")
    service_url = activity.get("serviceUrl")
    if not isinstance(raw_id, str) or not isinstance(service_url, str):
        return None
    channel_data = activity.get("channelData") or {}
    channel = channel_data.get("channel") or {}
    team = channel_data.get("team") or {}
    name = conversation.get("name") or channel.get("name") or team.get("name")
    return ConversationRef(
        conversation_id=raw_id.split(";messageid=")[0],
        service_url=service_url,
        conversation_type=str(conversation.get("conversationType") or "personal"),
        tenant_id=conversation.get("tenantId") or (channel_data.get("tenant") or {}).get("id"),
        name=str(name)[:255] if name else None,
    )


def _thread_root(activity: dict[str, Any]) -> str:
    """The channel thread an activity belongs to, or `""` in a chat, which has none.

    A reply in a channel names its thread in the conversation id; a new post is the
    root of the thread its answer will open.
    """
    conversation = activity.get("conversation") or {}
    if conversation.get("conversationType") != "channel":
        return ""
    _, _, root = str(conversation.get("id", "")).partition(";messageid=")
    return root or str(activity.get("id") or "")


def chat_id_of(activity: dict[str, Any]) -> str | None:
    """`platform_chat_id` for an activity: the conversation's key, and its thread if any."""
    ref = conversation_of(activity)
    if ref is None:
        return None
    return thread_key(ref.key, thread_id=_thread_root(activity), message_id=None)


def _sender(activity: dict[str, Any]) -> tuple[str, str | None]:
    sender = activity.get("from") or {}
    return str(sender.get("aadObjectId") or sender.get("id") or ""), sender.get("name")


def _plain(text: str, bot_mentions: list[str]) -> str:
    """The message as the person wrote it: the bot's own mention gone, markup undone."""
    for mention in bot_mentions:
        text = text.replace(mention, " ")
    text = _AT_TAG.sub(r"@\1", text)
    text = _TAG.sub("", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def _chunks(text: str) -> list[str]:
    """The text in pieces Teams will take, each cut at a line break where one is near."""
    pieces: list[str] = []
    rest = text
    while len(rest.encode("utf-8")) > MESSAGE_LIMIT_BYTES:
        fits = rest.encode("utf-8")[:MESSAGE_LIMIT_BYTES].decode("utf-8", errors="ignore")
        cut = len(fits)
        newline = rest.rfind("\n", 0, cut)
        if newline > cut // 2:
            cut = newline + 1
        pieces.append(rest[:cut])
        rest = rest[cut:]
    pieces.append(rest)
    return pieces


def _download_ceiling() -> int:
    """The most a fetched attachment may hold: the larger of what either caller takes.

    A file goes to chat storage and a voice message to transcription, and each
    caller checks the bytes against its own limit afterwards; this only stops
    the download from outgrowing both.
    """
    return max(settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024, TRANSCRIPTION_MAX_BYTES)


def _card(text: str, choices: list[ChannelChoice]) -> dict[str, Any]:
    """An Adaptive Card with the text and a button per choice."""
    styles = {"primary": "positive", "danger": "destructive"}
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [{"type": "TextBlock", "text": text, "wrap": True}],
        "actions": [
            {
                "type": "Action.Execute",
                "title": choice.label[:80],
                "verb": PRESS_VERB,
                "data": {PRESS_VERB: choice.value},
                **({"style": styles[choice.style]} if choice.style in styles else {}),
            }
            for choice in choices
        ],
    }


class TeamsAdapter(ChannelAdapter):
    """Teams, over HTTP. Every bot it serves is registered with its own credentials."""

    platform = "teams"

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        # Addresses an activity names outside the Bot Connector - where a shared
        # file is, where an accepted one is uploaded - come from what a Teams
        # client sent, so every hop is SSRF-checked and pinned. Never given the
        # bot's token: that goes to a Connector address only, on `_client`.
        self._outside = PinnedAsyncClient(timeout=httpx2.Timeout(20.0))
        self.auth = TeamsAuth(self._client)
        self._refs: dict[str, ConversationRef] = {}
        self._credentials: dict[str, TeamsCredentials] = {}

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._outside.aclose()

    def remember(self, bot_id: str, credentials: TeamsCredentials, ref: ConversationRef) -> None:
        """What the next reply needs: this bot's credentials and where the conversation lives."""
        self._credentials[bot_id] = credentials
        self.know(ref)

    def know(self, ref: ConversationRef) -> None:
        """Where a conversation lives, for a post that starts nowhere near an activity."""
        self._refs[ref.key] = ref

    async def _ref(self, key: str) -> ConversationRef:
        if key in self._refs:
            return self._refs[key]
        from app.db.session import get_db_context
        from app.repositories import teams_conversation_repo

        async with get_db_context() as db:
            row = await teams_conversation_repo.get_by_key(db, key)
        if row is None:
            raise ChannelNotConfigured(f"No Teams conversation is known as {key}")
        ref = ConversationRef(
            conversation_id=row.conversation_id,
            service_url=row.service_url,
            conversation_type=row.conversation_type,
            tenant_id=row.tenant_id,
            name=row.name,
        )
        self._refs[key] = ref
        return ref

    async def _target(self, platform_chat_id: str) -> tuple[ConversationRef, str]:
        """The conversation to post into, as Teams names it - a channel thread included."""
        key, root = split_thread(platform_chat_id)
        ref = await self._ref(key)
        if not is_connector_url(ref.service_url):
            raise ChannelNotConfigured("That conversation's service is not a Bot Connector")
        target = f"{ref.conversation_id};messageid={root}" if root else ref.conversation_id
        return ref, target

    async def _headers(self, credentials: TeamsCredentials) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.auth.access_token(credentials)}"}

    async def _post_activity(
        self, credentials: TeamsCredentials, platform_chat_id: str, activity: dict[str, Any]
    ) -> str | None:
        ref, target = await self._target(platform_chat_id)
        url = f"{ref.service_url.rstrip('/')}/v3/conversations/{target}/activities"
        response = await self._client.post(
            url, json=activity, headers=await self._headers(credentials)
        )
        response.raise_for_status()
        sent = response.json() if response.content else {}
        return str(sent["id"]) if isinstance(sent, dict) and sent.get("id") else None

    async def _put_activity(
        self,
        credentials: TeamsCredentials,
        platform_chat_id: str,
        activity_id: str,
        activity: dict[str, Any],
    ) -> None:
        ref, target = await self._target(platform_chat_id)
        url = f"{ref.service_url.rstrip('/')}/v3/conversations/{target}/activities/{activity_id}"
        response = await self._client.put(
            url, json={**activity, "id": activity_id}, headers=await self._headers(credentials)
        )
        response.raise_for_status()

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Post an answer: its text in pieces Teams takes, then its picture and files."""
        credentials = TeamsCredentials.decode(bot_token)
        ref, _ = await self._target(msg.platform_chat_id)
        pieces = _chunks(msg.text) if msg.text else []
        images, files = self._split_attachments(msg)
        for index, piece in enumerate(pieces):
            last = index == len(pieces) - 1
            await self._post_activity(
                credentials,
                msg.platform_chat_id,
                {
                    "type": "message",
                    "text": piece,
                    "textFormat": "markdown",
                    "attachments": images if last else [],
                },
            )
        if not pieces and images:
            await self._post_activity(
                credentials,
                msg.platform_chat_id,
                {"type": "message", "attachments": images},
            )
        for attachment in files:
            await self._offer_file(credentials, msg.platform_chat_id, ref, attachment)

    @staticmethod
    def _split_attachments(
        msg: OutgoingMessage,
    ) -> tuple[list[dict[str, Any]], list[OutgoingAttachment]]:
        """Pictures, drawn inline from the message itself; everything else, offered as a file."""
        images: list[dict[str, Any]] = []
        files: list[OutgoingAttachment] = []
        pictures = list(msg.attachments)
        if msg.image_png is not None:
            pictures.insert(0, OutgoingAttachment(msg.image_filename, msg.image_png, "image/png"))
        for attachment in pictures:
            if attachment.mime_type.startswith("image/"):
                encoded = base64.b64encode(attachment.content).decode("ascii")
                images.append(
                    {
                        "contentType": attachment.mime_type,
                        "contentUrl": f"data:{attachment.mime_type};base64,{encoded}",
                        "name": attachment.filename,
                    }
                )
            else:
                files.append(attachment)
        return images, files

    async def _offer_file(
        self,
        credentials: TeamsCredentials,
        platform_chat_id: str,
        ref: ConversationRef,
        attachment: OutgoingAttachment,
    ) -> None:
        """Ask the person to accept a file, which Teams then lets the bot upload.

        Teams takes a file from a bot only in a personal chat, and only once the
        person accepts it; elsewhere the answer names the file instead of
        dropping it without a word.
        """
        if ref.conversation_type != "personal" or _pending_files is None:
            await self._post_activity(
                credentials,
                platform_chat_id,
                {
                    "type": "message",
                    "text": f"📎 {attachment.filename} - files reach Teams in a personal chat.",
                },
            )
            return
        pending = uuid.uuid4().hex
        await _pending_files.set(
            f"teams:file:{pending}",
            base64.b64encode(attachment.content).decode("ascii"),
            ttl=FILE_CONSENT_TTL_SECONDS,
        )
        context = {"pending": pending, "name": attachment.filename}
        await self._post_activity(
            credentials,
            platform_chat_id,
            {
                "type": "message",
                "attachments": [
                    {
                        "contentType": FILE_CONSENT_CARD,
                        "name": attachment.filename,
                        "content": {
                            "description": attachment.filename,
                            "sizeInBytes": len(attachment.content),
                            "acceptContext": context,
                            "declineContext": context,
                        },
                    }
                ],
            },
        )

    async def complete_file_consent(
        self, bot_token: str, activity: dict[str, Any], platform_chat_id: str
    ) -> None:
        """Upload a file the person just accepted, and post it into the chat.

        A decline, an unknown or expired file, or an upload address that is not
        HTTPS ends quietly: the card is all the person asked about, and they can
        ask again.
        """
        value = activity.get("value") or {}
        context = value.get("context") or {}
        pending = context.get("pending")
        if _pending_files is None or not isinstance(pending, str):
            return
        stored = await _pending_files.getdel(f"teams:file:{pending}")
        if value.get("action") != "accept" or stored is None:
            return
        upload = value.get("uploadInfo") or {}
        upload_url = str(upload.get("uploadUrl") or "")
        if not upload_url.startswith("https://"):
            return
        content = base64.b64decode(stored)
        try:
            response = await self._outside.put(
                upload_url,
                content=content,
                headers={
                    "Content-Length": str(len(content)),
                    "Content-Range": f"bytes 0-{len(content) - 1}/{len(content)}",
                },
            )
        except UrlRefusedError:
            logger.warning("teams_upload_refused")
            return
        response.raise_for_status()
        await self._post_activity(
            TeamsCredentials.decode(bot_token),
            platform_chat_id,
            {
                "type": "message",
                "attachments": [
                    {
                        "contentType": FILE_INFO_CARD,
                        "contentUrl": upload.get("contentUrl"),
                        "name": upload.get("name") or context.get("name"),
                        "content": {
                            "uniqueId": upload.get("uniqueId"),
                            "fileType": upload.get("fileType"),
                        },
                    }
                ],
            },
        )

    async def begin_reply(self, bot_token: str, msg: OutgoingMessage) -> str | None:
        """Post the placeholder an answer is written into, and return its activity id."""
        return await self._post_activity(
            TeamsCredentials.decode(bot_token),
            msg.platform_chat_id,
            {"type": "message", "text": msg.text, "textFormat": "markdown"},
        )

    async def update_reply(self, bot_token: str, msg: OutgoingMessage, handle: str) -> None:
        await self._put_activity(
            TeamsCredentials.decode(bot_token),
            msg.platform_chat_id,
            handle,
            {"type": "message", "text": _chunks(msg.text)[0], "textFormat": "markdown"},
        )

    async def typing(self, bot_id: str, msg: OutgoingMessage) -> None:
        credentials = self._credentials.get(bot_id)
        if credentials is None:
            return
        try:
            await self._post_activity(credentials, msg.platform_chat_id, {"type": "typing"})
        except httpx.HTTPError, ChannelNotConfigured:
            logger.debug("teams_typing_failed", exc_info=True)

    async def send_prompt(self, bot_token: str, prompt: PromptMessage) -> None:
        """An approval or a question as an Adaptive Card, a button per choice."""
        await self._post_activity(
            TeamsCredentials.decode(bot_token),
            prompt.platform_chat_id,
            {
                "type": "message",
                "attachments": [
                    {"contentType": ADAPTIVE_CARD, "content": _card(prompt.text, prompt.choices)}
                ],
            },
        )

    async def settle_prompt(self, bot_token: str, press: IncomingPress, text: str) -> None:
        """Replace the card that was pressed with what was chosen."""
        if not press.message_id:
            return
        await self._put_activity(
            TeamsCredentials.decode(bot_token),
            press.platform_chat_id,
            press.message_id,
            {"type": "message", "text": text, "textFormat": "markdown"},
        )

    async def vouched_email(self, bot_token: str, incoming: IncomingMessage) -> str | None:
        """The sender's address, as the tenant's directory has it - when it signs people in here.

        Only where this deployment's own sign-in is Entra, in the tenant the bot
        is registered in: then the roster's address is the one somebody signed in
        with, and a Teams account can be linked to its member without a link
        (#1419). In any other tenant the address is just text somebody else's
        directory holds.
        """
        credentials = TeamsCredentials.decode(bot_token)
        issuer = settings.OIDC_ISSUER.rstrip("/").lower()
        tenant = credentials.tenant_id.lower()
        if not (
            issuer.startswith("https://login.microsoftonline.com/")
            and f"/{tenant}/" in f"{issuer}/"
        ):
            return None
        ref, _ = await self._target(incoming.platform_chat_id)
        if (ref.tenant_id or "").lower() != tenant:
            return None
        url = (
            f"{ref.service_url.rstrip('/')}/v3/conversations/{ref.conversation_id}"
            f"/members/{incoming.platform_user_id}"
        )
        response = await self._client.get(url, headers=await self._headers(credentials))
        if response.is_error:
            return None
        member = response.json()
        if (member.get("tenantId") or tenant).lower() != tenant:
            return None
        email = member.get("email") or member.get("userPrincipalName")
        return str(email).lower() if email else None

    async def welcome(
        self,
        bot_token: str,
        email: str,
        text: str,
        *,
        api_base_url: str | None,
        places: Sequence[str] = (),
    ) -> bool:
        """Find the person in the rosters of `places` and greet them in a personal chat.

        Teams has no directory a bot may search, but a member of any team or
        group chat the bot is in is on its roster, with their address. A personal
        chat is then opened through the Connector - which a bot may do for
        anybody in its own tenant - and the greeting posted there.
        """
        credentials = TeamsCredentials.decode(bot_token)
        wanted = email.lower()
        for key in places:
            ref = await self._ref(key)
            if not is_connector_url(ref.service_url):
                continue
            member_id = await self._member_id_by_email(credentials, ref, wanted)
            if member_id is None:
                continue
            headers = await self._headers(credentials)
            service = ref.service_url.rstrip("/")
            opened = await self._client.post(
                f"{service}/v3/conversations",
                json={
                    "bot": {"id": f"28:{credentials.app_id}"},
                    "members": [{"id": member_id}],
                    "isGroup": False,
                    "tenantId": credentials.tenant_id,
                    "channelData": {"tenant": {"id": credentials.tenant_id}},
                },
                headers=headers,
            )
            opened.raise_for_status()
            sent = await self._client.post(
                f"{service}/v3/conversations/{opened.json()['id']}/activities",
                json={"type": "message", "text": text},
                headers=headers,
            )
            sent.raise_for_status()
            return True
        return False

    async def _member_id_by_email(
        self, credentials: TeamsCredentials, ref: ConversationRef, email: str
    ) -> str | None:
        """The roster id of whoever in this conversation has `email`, page by page."""
        token: str | None = None
        while True:
            params = {"pageSize": "500"}
            if token:
                params["continuationToken"] = token
            response = await self._client.get(
                f"{ref.service_url.rstrip('/')}/v3/conversations/{ref.conversation_id}/pagedmembers",
                params=params,
                headers=await self._headers(credentials),
            )
            response.raise_for_status()
            page = response.json()
            for member in page.get("members", []):
                address = member.get("email") or member.get("userPrincipalName") or ""
                if str(address).lower() == email and member.get("id"):
                    return str(member["id"])
            token = page.get("continuationToken")
            if not token:
                return None

    async def channel_details(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None
    ) -> ChannelDetails:
        ref = await self._ref(split_thread(channel_id)[0])
        members = await self._members(bot_token, ref, limit=500)
        return ChannelDetails(
            channel_id=channel_id,
            name=ref.name or ref.conversation_type,
            is_private=ref.conversation_type != "channel",
            member_count=len(members),
        )

    async def channel_members(
        self, bot_token: str, channel_id: str, *, api_base_url: str | None, limit: int
    ) -> list[ChannelMember]:
        ref = await self._ref(split_thread(channel_id)[0])
        return await self._members(bot_token, ref, limit=limit)

    async def _members(
        self, bot_token: str, ref: ConversationRef, *, limit: int
    ) -> list[ChannelMember]:
        """The conversation's roster, one Connector page at a time."""
        credentials = TeamsCredentials.decode(bot_token)
        members: list[ChannelMember] = []
        token: str | None = None
        while len(members) < limit:
            params = {"pageSize": str(min(500, limit - len(members)))}
            if token:
                params["continuationToken"] = token
            response = await self._client.get(
                f"{ref.service_url.rstrip('/')}/v3/conversations/{ref.conversation_id}/pagedmembers",
                params=params,
                headers=await self._headers(credentials),
            )
            response.raise_for_status()
            page = response.json()
            for member in page.get("members", []):
                members.append(
                    ChannelMember(
                        user_id=str(member.get("aadObjectId") or member.get("id")),
                        username=member.get("userPrincipalName") or member.get("email"),
                        display_name=member.get("name"),
                    )
                )
            token = page.get("continuationToken")
            if not token:
                break
        return members[:limit]

    async def is_channel_member(
        self, bot_token: str, channel_id: str, platform_user_id: str, *, api_base_url: str | None
    ) -> bool:
        credentials = TeamsCredentials.decode(bot_token)
        ref = await self._ref(split_thread(channel_id)[0])
        response = await self._client.get(
            f"{ref.service_url.rstrip('/')}/v3/conversations/{ref.conversation_id}"
            f"/members/{platform_user_id}",
            headers=await self._headers(credentials),
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """Fetch a file somebody sent.

        A file in a personal chat arrives with a pre-authorised download URL; a
        picture pasted into a message is held by the Connector and needs the
        bot's token - which is sent nowhere but a Connector address.

        Read in chunks and abandoned past `_download_ceiling()`: a pasted
        picture states no size, so the callers' check against the claim passes
        it, and buffering the whole body before their check on the bytes would
        let one large file take a worker's memory.

        Raises:
            ValueError: For an address that is not HTTPS, one outside the Connector
                that the SSRF policy refuses (`UrlRefusedError`), or a body past the
                ceiling.
        """
        if not attachment.handle.startswith("https://"):
            raise ValueError("A Teams attachment is fetched over HTTPS only")
        ceiling = _download_ceiling()
        received = bytearray()

        def keep(chunk: bytes) -> None:
            received.extend(chunk)
            if len(received) > ceiling:
                raise ValueError(f"A Teams attachment is larger than {ceiling // (1024 * 1024)} MB")

        if is_connector_url(attachment.handle):
            headers = await self._headers(TeamsCredentials.decode(bot_token))
            async with self._client.stream("GET", attachment.handle, headers=headers) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    keep(chunk)
        else:
            async with self._outside.stream("GET", attachment.handle) as outside:
                outside.raise_for_status()
                async for chunk in outside.aiter_bytes():
                    keep(chunk)
        return bytes(received)

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Teams has nothing to poll: it posts every activity to the bot's endpoint."""

    async def stop_polling(self, bot_id: str) -> None:
        """Nothing was started."""

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """The messaging endpoint is set on the Azure Bot resource, not through an API.

        Logged so an operator has the address to paste.
        """
        logger.info("Teams: set the Azure Bot's messaging endpoint to %s", url)
        return False

    async def delete_webhook(self, bot_token: str) -> bool:
        return False

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Never: a Teams activity is verified by its token, which needs the network.

        The route calls `auth.verify` instead. Answering False here means no
        caller that reaches for the shared-secret check can believe a Teams
        request by mistake.
        """
        return False

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """A message activity as the router's message, or None for anything else."""
        if raw_payload.get("type") != "message":
            return None
        chat_id = chat_id_of(raw_payload)
        user_id, name = _sender(raw_payload)
        if chat_id is None or not user_id:
            return None
        recipient = (raw_payload.get("recipient") or {}).get("id")
        bot_mentions = [
            str(entity.get("text") or "")
            for entity in raw_payload.get("entities") or []
            if entity.get("type") == "mention"
            and (entity.get("mentioned") or {}).get("id") == recipient
            and entity.get("text")
        ]
        conversation_type = (raw_payload.get("conversation") or {}).get("conversationType")
        personal = conversation_type in (None, "personal")
        attachments = self._attachments(raw_payload)
        text = _plain(str(raw_payload.get("text") or ""), bot_mentions)
        if not text and not attachments:
            return None
        return IncomingMessage(
            platform=self.platform,
            bot_id=bot_id,
            platform_user_id=user_id,
            platform_chat_id=chat_id,
            chat_type="private" if personal else "group",
            text=text,
            raw=raw_payload,
            platform_username=name,
            platform_display_name=name,
            message_id=str(raw_payload["id"]) if raw_payload.get("id") else None,
            # Teams sends a bot a channel or group message only when it is
            # mentioned, unless the app was granted every message in the team.
            addressed=None if personal else bool(bot_mentions),
            attachments=attachments,
        )

    @staticmethod
    def _attachments(activity: dict[str, Any]) -> list[IncomingAttachment]:
        files: list[IncomingAttachment] = []
        for attachment in activity.get("attachments") or []:
            content_type = str(attachment.get("contentType") or "")
            name = str(attachment.get("name") or "")
            if content_type == FILE_DOWNLOAD_INFO:
                url = (attachment.get("content") or {}).get("downloadUrl")
                if url:
                    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    files.append(IncomingAttachment(name or "file", mime, 0, str(url)))
            elif content_type.startswith("image/") and attachment.get("contentUrl"):
                extension = mimetypes.guess_extension(content_type) or ".png"
                files.append(
                    IncomingAttachment(
                        name or f"image{extension}", content_type, 0, str(attachment["contentUrl"])
                    )
                )
        return files

    def parse_press(self, activity: dict[str, Any], bot_id: str) -> IncomingPress | None:
        """A press on one of the bot's cards, or None for an invoke that is not one.

        Who pressed comes from the activity the Connector signed, so the decision
        is recorded against them - not against whoever asked the question.
        """
        if activity.get("type") != "invoke" or activity.get("name") != "adaptiveCard/action":
            return None
        action = (activity.get("value") or {}).get("action") or {}
        value = (action.get("data") or {}).get(PRESS_VERB)
        chat_id = chat_id_of(activity)
        user_id, name = _sender(activity)
        if action.get("verb") != PRESS_VERB or not isinstance(value, str) or chat_id is None:
            return None
        if not user_id:
            return None
        return IncomingPress(
            platform=self.platform,
            bot_id=bot_id,
            platform_user_id=user_id,
            platform_chat_id=chat_id,
            value=value,
            platform_username=name,
            message_id=activity.get("replyToId"),
        )


def teams_adapter() -> TeamsAdapter:
    """The registered adapter, or one registered now - a worker posting a trigger's result.

    The API registers it at startup; the job worker (`python -m app.worker`) never
    does, and a trigger fired there still has to reach Teams.
    """
    from app.services.channels import get_adapter, register_adapter

    try:
        adapter = get_adapter(TeamsAdapter.platform)
    except KeyError:
        adapter = TeamsAdapter()
        register_adapter(adapter)
    if not isinstance(adapter, TeamsAdapter):  # pragma: no cover - registered by platform
        raise TypeError("The adapter registered for Teams is not the Teams adapter")
    return adapter
