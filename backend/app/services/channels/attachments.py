"""Files across a channel, in both directions.

Giving an agent a filesystem while the two surfaces where people actually share
files could not put anything into it was half a feature: `IncomingMessage` had no
attachment field at all, so a spreadsheet dropped into Slack was discarded and the
agent answered about a document it never received.

**Inbound is the web upload path, reached differently.** The bytes arrive from a
platform instead of a browser, and then go through exactly what
`FileUploadService.upload` applies: the MIME allowlist, `MAX_UPLOAD_SIZE`, the
parser, storage, and a `ChatFile` row. A bot is the most permissive edge this
platform has - anyone in a Slack channel can drop a file on it - so it must not
also become the lenient one.

The size is checked twice, deliberately. Once against what the platform *claims*
before anything is fetched, because downloading a gigabyte to then reject it is
the attack; and once against the bytes, because a claim is not a measurement.

**Outbound is what the agent wrote this turn.** Not a diff of the whole workspace:
`/uploads` is what the *user* sent - posting it back is quoting somebody their own
file - and `/skills` is materialised know-how the platform put there, not the
agent's work. What is left is what the turn produced, capped, with anything too
large named in the reply rather than silently dropped: an agent told its file was
delivered when it was not will confidently tell the user the same.
"""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai_backends import AsyncBackendProtocol, BackendProtocol, ensure_async
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chat_file import ChatFile
from app.services.channels.base import (
    ChannelAdapter,
    IncomingAttachment,
    OutgoingAttachment,
)
from app.services.file_upload import FileUploadService

logger = logging.getLogger(__name__)

MAX_OUTBOUND_FILES = 3
"""How many files one reply may carry.

A turn that writes twelve intermediate CSVs should not post twelve of them into a
channel. Three is enough for "the report, the chart and the log" and few enough
that the reply is still a reply; the rest stay in the workspace, which the reply
says.
"""

MAX_OUTBOUND_BYTES = 8 * 1024 * 1024
"""Below every one of these platforms' own limits, so the refusal is ours and can
be explained. Telegram's is 50 MB, Slack's depends on the workspace plan, and a
platform-side rejection arrives as an opaque API error the agent cannot act on."""

# Where the platform itself put things. Neither is the agent's work, and neither
# should come back out: `/uploads` is the user's own file, and `/skills` is
# organizational know-how materialised for the run.
_NOT_THE_AGENTS = ("/uploads/", "/skills/")


@dataclass(frozen=True)
class DeliveredFiles:
    """What a reply can carry, and what it has to explain instead."""

    attachments: list[OutgoingAttachment]
    refused: list[str]
    """Files named in the reply because they could not be posted - too large, or
    past the per-reply cap. Named rather than dropped: an agent told its file was
    delivered will tell the user the same."""

    def note(self) -> str:
        """One line for the reply about what did not make it, or nothing."""
        if not self.refused:
            return ""
        names = ", ".join(self.refused)
        return (
            f"({names} stayed in the workspace - too large to post here, "
            "or past the file limit for one reply.)"
        )


class ChannelAttachmentService:
    """Fetches what somebody sent, and picks what to send back."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.uploads = FileUploadService(db)

    async def receive(
        self,
        adapter: ChannelAdapter,
        bot_token: str,
        attachments: list[IncomingAttachment],
        *,
        user_id: UUID,
    ) -> tuple[list[ChatFile], list[str]]:
        """Fetch, validate and store what arrived with a message.

        Returns the rows that made it and a message per file that did not, for the
        reply to carry. A refusal is reported rather than raised: one unsupported
        file among three should not lose the other two or the question that came
        with them.

        `user_id` is the sender's **linked account**, which a channel run already
        requires - the mention router refuses an unlinked sender before this is
        reached - so a stored file belongs to the person who sent it rather than
        to nobody.
        """
        stored: list[ChatFile] = []
        refusals: list[str] = []

        for attachment in attachments:
            # Checked against the claim first: fetching a gigabyte in order to
            # reject it is the thing worth not doing.
            valid, error = self.uploads.validate_upload(attachment.mime_type, attachment.size)
            if not valid:
                refusals.append(f"{attachment.filename}: {_why(attachment, error)}")
                continue
            try:
                data = await adapter.download_attachment(bot_token, attachment)
            except NotImplementedError:
                refusals.append(
                    f"{attachment.filename}: this build cannot fetch files from "
                    f"{adapter.platform} yet."
                )
                continue
            except Exception:
                logger.warning(
                    "channel_attachment_download_failed",
                    # `attachment_name`, not `filename`: that key belongs to
                    # `LogRecord` and overwriting it renames the source file in
                    # every formatter that prints one.
                    extra={"platform": adapter.platform, "attachment_name": attachment.filename},
                    exc_info=True,
                )
                refusals.append(f"{attachment.filename}: could not be downloaded.")
                continue

            # Again, against the bytes. A platform that under-reported the size,
            # or a handle that resolved to something else, gets caught here.
            valid, error = self.uploads.validate_upload(attachment.mime_type, len(data))
            if not valid:
                refusals.append(f"{attachment.filename}: {_why(attachment, error)}")
                continue

            stored.append(
                await self.uploads.upload(
                    user_id=user_id,
                    file_data=data,
                    filename=attachment.filename,
                    content_type=attachment.mime_type,
                )
            )

        return stored, refusals


def _why(attachment: IncomingAttachment, error: str | None) -> str:
    """Why a file was turned away, in terms of what somebody actually sent.

    Voice notes are the case this exists for. Somebody sends one, and "File type
    'audio/ogg' is not supported" reads as a platform that cannot handle files -
    when the truth is narrower and more useful: the file arrived, and nothing here
    can listen to it yet.

    Delete this along with the branch once transcription lands (#54); until then a
    generic message would send people looking for a bug that is not there.
    """
    if attachment.mime_type.startswith(("audio/", "video/")):
        return (
            "I cannot listen to recordings yet - transcription is not wired up. "
            "Type it out, or send a file."
        )
    return error or "not supported."


async def files_written(
    backend: BackendProtocol | AsyncBackendProtocol, before: set[str] | None
) -> DeliveredFiles:
    """What the agent produced this turn, ready to post.

    `before` is the set of paths the workspace held when the turn started, so this
    is what the turn *added*. Compared against a snapshot rather than against
    modification times: a state backend has none, and a container's clock is not
    ours to trust.

    `None` means the snapshot could not be taken, and nothing is posted. It cannot
    be treated as "the workspace was empty": this function answers
    `paths - before`, so an empty `before` makes *every file in the workspace* read
    as this turn's output - and under `agent` or `channel` scope those are
    somebody else's files, on their way into a shared channel. Posting nothing is
    the failure worth having.

    A file the agent overwrote is deliberately not included. Rewriting a file it
    already had is ordinary work - a script it is iterating on - and posting it on
    every turn would fill the channel with the same attachment.

    Never raises. This runs after an answer somebody is waiting for; a workspace
    that cannot be listed means a reply with no attachments, not a lost reply.
    """
    if before is None:
        return DeliveredFiles(attachments=[], refused=[])
    reader = ensure_async(backend)
    try:
        paths = await _workspace_paths(reader)
    except Exception:
        logger.warning("outbound_attachment_scan_failed", exc_info=True)
        return DeliveredFiles(attachments=[], refused=[])

    new = sorted(paths - before)
    attachments: list[OutgoingAttachment] = []
    refused: list[str] = []

    for path in new:
        if path.startswith(_NOT_THE_AGENTS):
            continue
        if len(attachments) >= MAX_OUTBOUND_FILES:
            refused.append(path)
            continue
        try:
            data = await reader.read_bytes(path)
        except Exception:
            logger.info("outbound_attachment_unreadable", extra={"path": path})
            continue
        if len(data) > MAX_OUTBOUND_BYTES:
            refused.append(path)
            continue
        attachments.append(
            OutgoingAttachment(
                filename=path.rsplit("/", 1)[-1],
                content=data,
                # Guessed from the name, not fixed at `application/octet-stream`.
                # A chart is the commonest thing an agent produces, and a PNG
                # posted as an opaque blob is a file somebody has to download to
                # find out it was the picture they asked for. Guessing from the
                # extension rather than sniffing the bytes: the name is what the
                # agent chose, and a wrong guess here costs a preview rather than
                # anything a platform acts on.
                mime_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            )
        )

    return DeliveredFiles(attachments=attachments, refused=refused)


async def workspace_snapshot(
    backend: BackendProtocol | AsyncBackendProtocol,
) -> set[str] | None:
    """Every path the workspace holds right now, or `None` if it could not be read.

    Taken before the turn so what it added can be told from what it already had.

    `None` rather than an empty set, which is the whole point of the return type.
    An empty set does not mean "nothing to compare against" - it means "the
    workspace was empty", and `files_written` answers `paths - before`, so every
    file already in the workspace would read as this turn's output. Under `agent`
    or `channel` scope those files belong to other people, and up to
    `MAX_OUTBOUND_FILES` of them would be posted into a shared channel.

    This needs only a *transient* failure to happen: both functions call
    `_workspace_paths`, so a persistently broken listing fails both and posts
    nothing. A remote host reached over HTTP is exactly what supplies a transient
    one.
    """
    try:
        return await _workspace_paths(ensure_async(backend))
    except Exception:
        logger.warning("workspace_snapshot_failed", exc_info=True)
        return None


async def _workspace_paths(backend: AsyncBackendProtocol) -> set[str]:
    """Every file in the workspace, dotfiles included.

    Two patterns, because `**/*` does not match a name beginning with a dot. Here it
    matters in the *safe* direction and still matters: a `.env` the agent wrote before
    the turn would be absent from the snapshot, so writing it again during the turn
    would read as new and get posted into the channel.

    Awaited rather than called: a container-backed workspace answers a glob over the
    network with a synchronous client, so two of them from a coroutine held the event
    loop for two round trips - once before the turn and once after.
    """
    return {
        str(entry["path"])
        for pattern in ("**/*", "**/.*")
        for entry in await backend.glob_info(pattern)
        if not entry.get("is_dir")
    }
