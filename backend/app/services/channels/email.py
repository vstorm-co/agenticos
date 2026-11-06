"""E-mail as a channel platform (#2082).

A person mails the bot's address and the message reaches an agent exactly like a direct
message on any other platform: through the same router, the same linked identity, the
same access policy and the same budgets. This module is only the transport.

**Inbound** arrives from a relay, not from a mailbox this process polls. Whatever receives
the mail - a Cloudflare Email Worker, a Postmark or Mailgun inbound route, a small script
on a mail server - posts one JSON document per message to the bot's webhook:

    {"from": "ada@acme.com", "sender_authentication": {"dmarc": "pass", "from": "ada@acme.com"},
     "subject": "...", "text": "...", "message_id": "<id@host>",
     "in_reply_to": "<id@host>", "references": ["<id@host>"],
     "attachments": [{"filename": "a.pdf", "content_type": "application/pdf",
                      "content_base64": "..."}]}

and signs it: `X-AgenticOS-Timestamp` (unix seconds) and `X-AgenticOS-Signature`
(`sha256=` + hex HMAC-SHA256 of `timestamp.body` under the bot's webhook secret). The
signature proves the relay sent it; it is *not* proof of who the sender is. A sender's
address is a claim, so a person acts with their AgenticOS permissions only once they have
linked that address to their account through the ordinary channel link. The relay must
attest a passing, aligned DMARC verdict for this message's exact header From in the
signed `sender_authentication` object. Compute it from trusted receiver results, never
sender-supplied headers. Missing, failed or mismatched proofs are ignored before identity,
prompt or attachment handling.

**Outbound** goes through the deployment's e-mail provider, from the bot's address, as
the reply to the sender's last message. A deployment on the `log` provider delivers
nothing, so a bot there refuses to pretend it answered.

An e-mail has no buttons, so a prompt is sent as numbered lines and the reply's first
line - a lone number - turns back into the press it stands for (`sms_prompts`, which
both channels share).
"""

import asyncio
import base64
import hashlib
import hmac
import html
import logging
import re
import time
from collections.abc import AsyncIterable
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn_after_rollback
from app.repositories import background_job as background_job_repo
from app.services.background_jobs import enqueue
from app.services.channels import email_state, sms_prompts
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.email import get_email_provider
from app.services.email.providers.base import EmailAttachment, EmailMessage
from app.worker.jobs import PROCESS_EMAIL_DELIVERY, EmailDelivery

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "x-agenticos-signature"
TIMESTAMP_HEADER = "x-agenticos-timestamp"
MAX_SKEW_SECONDS = 5 * 60
"""How far a signed request's clock may be from ours: wide enough for a relay's, narrow
enough that a captured request cannot be replayed tomorrow."""

MAX_BODY_BYTES = 25 * 1024 * 1024
MAX_RETAINED_DELIVERY_BYTES = 256 * 1024 * 1024
MAX_RETAINED_DELIVERIES = 4096
MAX_ATTACHMENTS = 10
PLATFORM = "email"

_ADDRESS = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_ATTRIBUTION = re.compile(
    r"^(on .{5,200} wrote:|-{2,}\s*original message\s*-{2,}|from:\s.+)$", re.I
)


class _SenderAuthentication(BaseModel):
    """A trusted relay's per-message DMARC verdict for the exact header From."""

    model_config = ConfigDict(extra="forbid", strict=True)
    dmarc: Literal["pass"]
    header_from: str = Field(alias="from", min_length=3, max_length=320)


def is_address(value: str) -> bool:
    return bool(_ADDRESS.match(value.strip()))


def sign(secret: str, timestamp: str, body: str) -> str:
    """The signature a relay puts on a request: `sha256=` and the hex HMAC of `timestamp.body`."""
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def reply_body(text: str) -> str:
    """What the person wrote, without the history their mail client quoted under it.

    Cut at the first quoted line or attribution ("On Tue, Ada wrote:"), because the agent
    already holds the thread and a quoted copy of its own last answer is noise at best.
    """
    kept: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith(">") or _ATTRIBUTION.match(stripped):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _html(text: str) -> str:
    paragraphs = (html.escape(part).replace("\n", "<br>") for part in text.split("\n\n"))
    return "".join(f"<p>{part}</p>" for part in paragraphs if part)


def _subject(thread: email_state.Thread | None) -> str:
    if thread is None or not thread.subject.strip():
        return "Message from your agent"
    subject = thread.subject.strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


class EmailAdapter(ChannelAdapter):
    platform = PLATFORM

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        """Send one mail to the sender's address, as the reply to their last one.

        `bot_token` is the bot's own address: what the mail comes from.

        Raises:
            ChannelNotConfigured: The token is not an address, or the deployment's e-mail
                provider delivers nothing.
            RuntimeError: The provider did not accept the message; the router records it.
        """
        sender = bot_token.strip()
        if not is_address(sender):
            raise ChannelNotConfigured("An e-mail bot's token is the address it sends from.")
        provider = get_email_provider()
        if not provider.delivers:
            raise ChannelNotConfigured(
                "This deployment's EMAIL_PROVIDER delivers nothing, so the bot cannot answer."
            )
        if not msg.text.strip() and not msg.attachments:
            return
        thread = await email_state.thread_of(sender.lower(), msg.platform_chat_id.lower())
        headers: dict[str, str] = {}
        if thread is not None and thread.message_id:
            headers["In-Reply-To"] = thread.message_id
            headers["References"] = " ".join(thread.references)
        result = await provider.send(
            EmailMessage(
                to=[msg.platform_chat_id],
                from_email=sender,
                subject=_subject(thread),
                text=msg.text,
                html=_html(msg.text),
                headers=headers,
                attachments=[
                    EmailAttachment(
                        filename=item.filename, content=item.content, mime_type=item.mime_type
                    )
                    for item in msg.attachments
                ],
            )
        )
        if not result.accepted:
            raise RuntimeError(result.error or "The e-mail provider did not accept the message.")

    async def send_prompt(self, bot_token: str, prompt: PromptMessage) -> None:
        """Send the question with its choices numbered, and remember what each number means."""
        chat = prompt.platform_chat_id.lower()
        start = await sms_prompts.reserve(
            prompt.bot_id, chat, len(prompt.choices), platform=PLATFORM
        )
        lines = [f"{number}. {choice.label}" for number, choice in enumerate(prompt.choices, start)]
        await self.send_message(
            bot_token,
            OutgoingMessage(
                platform_chat_id=prompt.platform_chat_id,
                text=f"{prompt.text}\n\n"
                + "\n".join(lines)
                + "\n\nReply to this e-mail with just the number.",
            ),
        )
        await sms_prompts.remember(
            prompt.bot_id,
            chat,
            [choice.value for choice in prompt.choices],
            start=start,
            platform=PLATFORM,
        )

    async def settle_prompt(self, bot_token: str, press: IncomingPress, text: str) -> None:
        await sms_prompts.settle(
            press.bot_id, press.platform_chat_id.lower(), press.value, platform=PLATFORM
        )

    async def download_attachment(self, bot_token: str, attachment: IncomingAttachment) -> bytes:
        """The file the relay sent inline, which waits briefly under its handle."""
        encoded = await email_state.take_attachment(attachment.handle)
        if encoded is None:
            raise ValueError("The attachment is no longer available; ask for it to be sent again.")
        return base64.b64decode(encoded)

    async def start_polling(self, bot_id: str, bot_token: str) -> None:
        """Mail arrives only through the relay's webhook; there is nothing to poll."""

    async def stop_polling(self, bot_id: str) -> None:
        return None

    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
        """The relay is configured by whoever runs it; the operator points it at `url`."""
        logger.info("Point the mail relay at %s", url)
        return True

    async def delete_webhook(self, bot_token: str) -> bool:
        return True

    def verify_webhook_signature(
        self, headers: dict[str, str], secret: str, body: str | None = None
    ) -> bool:
        """Whether the relay signed this request recently with `secret`.

        Compared in constant time. No signature, no timestamp, a stale or non-numeric
        timestamp, or no body is not the relay's.
        """
        given = headers.get(SIGNATURE_HEADER)
        stamp = headers.get(TIMESTAMP_HEADER)
        if not given or not stamp or body is None or not stamp.isdigit():
            return False
        if abs(time.time() - int(stamp)) > MAX_SKEW_SECONDS:
            return False
        return hmac.compare_digest(given, sign(secret, stamp, body))

    def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
        """A mail from an address. One with no sender, or neither text nor files, is ignored."""
        sender = str(raw_payload.get("from") or "").strip().lower()
        if not is_address(sender):
            return None
        try:
            proof = _SenderAuthentication.model_validate(raw_payload.get("sender_authentication"))
        except ValidationError:
            return None
        if proof.header_from.strip().lower() != sender:
            return None
        text = reply_body(str(raw_payload.get("text") or ""))
        message_id = str(raw_payload.get("message_id") or "") or None
        if message_id is not None and (
            len(message_id) > 998 or "\n" in message_id or "\r" in message_id
        ):
            return None
        if _reference_ids(raw_payload.get("references")) is None:
            return None
        attachments = self._attachments(raw_payload.get("attachments"), bot_id)
        if not text and not attachments:
            return None
        return IncomingMessage(
            platform=self.platform,
            bot_id=bot_id,
            platform_user_id=sender,
            platform_chat_id=sender,
            chat_type="private",
            text=text,
            raw=raw_payload,
            message_id=message_id,
            addressed=True,
            attachments=attachments,
        )

    @staticmethod
    def _attachments(raw: Any, bot_id: str) -> list[IncomingAttachment]:
        if not isinstance(raw, list):
            return []
        delivery = uuid4().hex
        found: list[IncomingAttachment] = []
        for index, item in enumerate(raw[:MAX_ATTACHMENTS]):
            if not isinstance(item, dict) or not isinstance(item.get("content_base64"), str):
                continue
            encoded = item["content_base64"]
            found.append(
                IncomingAttachment(
                    filename=str(item.get("filename") or f"attachment-{index + 1}"),
                    mime_type=str(item.get("content_type") or "application/octet-stream"),
                    size=len(encoded) * 3 // 4,
                    handle=f"{bot_id}:{delivery}:{index}",
                )
            )
        return found


def _reference_ids(value: object) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    references: list[str] = []
    for item in value[-email_state.MAX_REFERENCES :]:
        if not isinstance(item, str) or len(item) > 998 or "\r" in item or "\n" in item:
            return None
        references.append(item)
    return references


async def keep_inbound(
    bot_token: str, incoming: IncomingMessage, payload: dict[str, Any]
) -> email_state.Thread | None:
    """Remember what the reply needs: the thread to answer into, and the files to read."""
    chain = _reference_ids(payload.get("references"))
    if chain is None:
        raise ValueError("Inbound email references must be validated before storage")
    subject = " ".join(str(payload.get("subject") or "").splitlines())[:998]
    thread = email_state.Thread(
        subject=subject,
        message_id=incoming.message_id,
        references=[*chain, *([incoming.message_id] if incoming.message_id else [])][
            -email_state.MAX_REFERENCES :
        ],
    )
    files = {
        attachment.handle: payload["attachments"][int(attachment.handle.rsplit(":", 1)[1])][
            "content_base64"
        ]
        for attachment in incoming.attachments
    }
    if not await email_state.stash_attachments(incoming.bot_id, files):
        return None
    try:
        await email_state.remember_thread(
            bot_token.strip().lower(),
            incoming.platform_chat_id,
            subject=subject,
            message_id=incoming.message_id,
            references=chain,
        )
    except BaseException:
        import anyio

        with anyio.CancelScope(shield=True):
            await email_state.discard_attachments(files)
        raise
    return thread


async def read_webhook_body(chunks: AsyncIterable[bytes], *, max_bytes: int) -> bytes | None:
    """Read the bounded relay form; None is an oversized delivery, never partial mail."""
    from app.core.exceptions import BadRequestError

    content = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in chunks:
                if len(content) + len(chunk) > max_bytes:
                    return None
                content.extend(chunk)
    except TimeoutError as exc:
        raise BadRequestError(message="The email webhook body timed out") from exc
    return bytes(content)


async def queue_delivery(
    db: AsyncSession,
    *,
    organization_id: UUID,
    bot_id: UUID,
    bot_address: str,
    body: str,
    incoming: IncomingMessage,
) -> bool:
    """Commit the complete signed delivery before acknowledging it; False means cache quota."""
    from app.db.locks import LockScope, hold_subject

    await hold_subject(db, LockScope.EMAIL_DELIVERY_STORAGE_PER_ORG, organization_id)
    key = (
        f"email:{bot_id}:{hashlib.sha256(incoming.message_id.encode()).hexdigest()}"
        if incoming.message_id
        else None
    )
    if (
        key is not None
        and await background_job_repo.get_by_idempotency_key(
            db, organization_id=organization_id, idempotency_key=key
        )
        is not None
    ):
        return True
    count, size = await background_job_repo.retained_payload_usage(
        db, organization_id=organization_id, kind=PROCESS_EMAIL_DELIVERY.kind
    )
    if count >= MAX_RETAINED_DELIVERIES or size + len(body.encode()) > MAX_RETAINED_DELIVERY_BYTES:
        return False
    thread = await keep_inbound(bot_address, incoming, incoming.raw)
    if thread is None:
        return False
    handles = [item.handle for item in incoming.attachments]
    try:
        async with db.begin_nested():
            await enqueue(
                db,
                PROCESS_EMAIL_DELIVERY,
                EmailDelivery(
                    organization_id=organization_id,
                    bot_id=bot_id,
                    body=body,
                    attachment_handles=handles,
                ),
                organization_id=organization_id,
                idempotency_key=key,
                concurrency_key=f"email:{bot_id}:{hashlib.sha256(incoming.platform_chat_id.encode()).hexdigest()}",
            )
    except BaseException as exc:
        import anyio

        with anyio.CancelScope(shield=True):
            await email_state.discard_attachments(handles)
        if isinstance(exc, IntegrityError) and key is not None:
            winner = await background_job_repo.get_by_idempotency_key(
                db, organization_id=organization_id, idempotency_key=key
            )
            if winner is not None:
                return True
        raise
    spawn_after_rollback(
        db, email_state.discard_attachments(handles), name=f"email_rollback:{bot_id}"
    )
    return True
