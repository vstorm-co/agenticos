"""Staging a mail's attachments as files of the run, for the mailbox triggers.

The poll lists a message's attachments and stores nothing (it holds the mailbox's
lock, and one message can start several runs); the trigger step stores them, here,
with the organization's own mailbox grant. What is stored is bounded by the chat
upload rules plus a count and a total per message, and what is not stored is
listed with the reason, so the graph can say "an attachment was left out".
"""

from collections.abc import Iterable

from app.core.config import settings
from app.db.session import get_worker_db_context
from app.services import portals
from app.services.file_upload import FileUploadService
from app.services.mcp_connection import McpConnectionService
from app.services.portals import AttachmentTooLarge, PortalUnreachable
from app.services.workflow_execution import context
from app.services.workflow_execution.exceptions import WorkflowFileQuotaError
from app.workflows import files
from app.workflows.contracts.results import Failed
from app.workflows.nodes._triggers import AttachmentSkip, EmailTriggerOutput, MailAttachment

MAX_STAGED_ATTACHMENTS = 10
MAX_STAGED_BYTES = 25 * 1024 * 1024
MAIL_ATTACHMENT_UNREACHABLE = "MAIL_ATTACHMENT_UNREACHABLE"

# A provider answering these says the attachment is gone, not ours to read, a bad id,
# or that the grant was revoked while its token still looked fresh: a retry cannot
# succeed, so the run goes on without it. Anything else is the provider being down.
_GONE = frozenset({400, 401, 403, 404})


class _Unreachable(Exception):
    """Carries the failed result out of `saved_batch`, so what this attempt stored is discarded."""

    def __init__(self, failed: Failed) -> None:
        self.failed = failed


def _skipped(attachment: MailAttachment, reason: AttachmentSkip) -> MailAttachment:
    return attachment.model_copy(update={"reason": reason})


async def stage_attachments(
    message: EmailTriggerOutput, *, portal_key: str, admitted_by: str
) -> EmailTriggerOutput | Failed:
    """The message with each attachment stored as a file of this run, or marked why not.

    A run that the mailbox did not admit (`admitted_by` is the trigger the mailbox
    admits as) reads nothing from it: its attachments are handed on `not_fetched`. So
    does one whose admission already marked them: the surface that started it left
    the files unstored because its graph reads none.

    Returns:
        The message with `attachments` filled in, or `MAIL_ATTACHMENT_UNREACHABLE`
        (retryable) when the provider failed for a reason a retry may cure, after
        discarding the files this attempt stored.
    """
    if not message.attachments or all(a.reason for a in message.attachments):
        return message
    if context.current().triggered_by != admitted_by:
        return _with(message, (_skipped(a, "not_fetched") for a in message.attachments))
    try:
        async with files.saved_batch() as batch:
            staged = await _stage(message, batch, portal_key=portal_key)
    except _Unreachable as exc:
        return exc.failed
    return _with(message, staged)


def _with(message: EmailTriggerOutput, attachments: Iterable[MailAttachment]) -> EmailTriggerOutput:
    return message.model_copy(update={"attachments": list(attachments)})


async def _stage(
    message: EmailTriggerOutput, batch: files.SavedFileBatch, *, portal_key: str
) -> list[MailAttachment]:
    adapter = portals.get_adapter(portal_key)
    max_file = settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    token: str | None = None
    token_asked = False
    total = 0
    staged: list[MailAttachment] = []
    for index, attachment in enumerate(message.attachments):
        if index >= MAX_STAGED_ATTACHMENTS:
            staged.append(_skipped(attachment, "too_many"))
            continue
        name = attachment.name
        allowed, _ = FileUploadService.validate_upload(attachment.content_type, 0, name)
        if not allowed:
            staged.append(_skipped(attachment, "type_not_allowed"))
            continue
        if attachment.byte_size is not None and (
            attachment.byte_size > max_file or attachment.byte_size > MAX_STAGED_BYTES - total
        ):
            staged.append(_skipped(attachment, "too_large"))
            continue
        if not token_asked:
            token_asked = True
            async with get_worker_db_context() as db:
                token = await McpConnectionService(db).portal_read_token(
                    organization_id=context.current().organization_id, portal_key=portal_key
                )
        if adapter is None or token is None:
            staged.append(_skipped(attachment, "unreadable"))
            continue
        try:
            data = await adapter.attachment(
                access_token=token,
                message_id=message.message_id,
                attachment_id=attachment.attachment_id,
                mailbox=message.mailbox or None,
                max_bytes=max_file,
            )
        except AttachmentTooLarge:
            staged.append(_skipped(attachment, "too_large"))
            continue
        except PortalUnreachable as exc:
            status = (exc.details or {}).get("status")
            if status in _GONE:
                staged.append(_skipped(attachment, "unreadable"))
                continue
            # The provider's words are never carried: its error echoes the request.
            raise _Unreachable(
                files.failed(
                    MAIL_ATTACHMENT_UNREACHABLE,
                    "The mailbox could not be read for an attachment; the step will be retried",
                    retryable=True,
                    portal_key=portal_key,
                    status=status,
                )
            ) from None
        valid, _ = FileUploadService.validate_bytes(data, attachment.content_type, name)
        if not valid:
            staged.append(_skipped(attachment, "type_not_allowed"))
            continue
        if total + len(data) > MAX_STAGED_BYTES:
            staged.append(_skipped(attachment, "too_large"))
            continue
        try:
            ref = await batch.save(data, content_type=files.sniff(data), filename=name)
        except WorkflowFileQuotaError:
            staged.append(_skipped(attachment, "quota"))
            continue
        total += len(data)
        staged.append(attachment.model_copy(update={"stored": True, "file": ref}))
    return staged
