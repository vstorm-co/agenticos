"""What happens to a file somebody attaches to a message.

Before a workspace existed there was one answer: parse it and paste the text
into the user's message. That works, and it costs the file's full token weight
on *every turn of the conversation, forever* - the model re-reads a two-hundred
page report to answer "and what about March". A fifty-megabyte CSV cannot be
attached at all.

With a workspace there is a better answer: put the file where the agent can
reach it, and give the model a reference plus enough of a head to decide whether
reading it is worth a tool call. The file stops being context and becomes data.

Images are the exception that keeps both paths. The model must still *see* the
picture - that is what multimodal models are for and a path string is not a
substitute - and it must also be able to act on it, which needs bytes on a
filesystem. So an image goes both ways, up to a ceiling past which paying for
the bytes twice stops being worth it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai.messages import BinaryContent
from pydantic_ai_backends import AsyncBackendProtocol, BackendProtocol, ensure_async

from app.core.config import settings
from app.db.models.chat_file import ChatFile
from app.services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

UPLOAD_DIR = "/uploads"
"""Where attachments land. One directory, so `ls /uploads` answers "what was I
given" without the agent guessing at a layout."""

HEAD_LINES = 20
"""How much of a text file the reference shows.

Enough for the model to tell a sales export from a log, and to know the column
names - which is what it needs to decide whether to read the rest. More would
start being the paste this exists to replace.
"""

HEAD_CHARS = 2000
"""A second bound, for a file whose twenty lines are one long line each."""

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_DOT_RUN = re.compile(r"\.{2,}")


@dataclass(frozen=True)
class AttachmentPlan:
    """What one attached file contributes to the turn."""

    reference: str | None
    """The text describing it, appended to the user's message."""

    inline: BinaryContent | None
    """Bytes the model should see directly, when it can and should."""


def workspace_path(chat_file: ChatFile) -> str:
    """Where this file lives in the workspace, derived from the file itself.

    The id goes in the name rather than into a mapping table, and that one
    choice buys two properties. Two files called `report.csv` cannot overwrite
    each other, and re-attaching the same file on a later turn resolves to the
    same path - so the write is skipped rather than repeated, which is the
    difference between an upload costing one write and costing one per turn for
    the rest of the conversation.
    """
    return f"{UPLOAD_DIR}/{chat_file.id.hex[:8]}-{safe_name(chat_file.filename)}"


def safe_name(filename: str) -> str:
    """A filename that cannot escape the uploads directory.

    The name is whatever the user's operating system allowed, which includes
    `../`, a leading dash and a thousand characters. Sanitised rather than
    rejected: the file is fine, only its name is hostile.

    Separators are already gone once the allowed alphabet is applied, so a run
    of dots cannot traverse anything. It is collapsed anyway: `_.._etc_passwd`
    is safe here and stops being obviously safe the moment somebody downstream
    splits a path differently, and the cost of not having to think about that
    again is one substitution.
    """
    cleaned = _DOT_RUN.sub("_", _UNSAFE.sub("_", filename.strip())).lstrip("._-")
    return cleaned[:96] or "attachment"


def _head(text: str) -> str:
    return "\n".join(text.splitlines()[:HEAD_LINES])[:HEAD_CHARS]


def _size(chat_file: ChatFile) -> str:
    if chat_file.size >= 1024 * 1024:
        return f"{chat_file.size / (1024 * 1024):.1f} MB"
    return f"{max(1, chat_file.size // 1024)} KB"


def _pasted(chat_file: ChatFile) -> str:
    """The whole file, inline. What every attachment used to get."""
    return f"\n---\nAttached file: {chat_file.filename}\n```\n{chat_file.parsed_content}\n```"


def _referenced(chat_file: ChatFile, path: str) -> str:
    parts = [
        f"\n---\nAttached file: {chat_file.filename} "
        f"({path}, {_size(chat_file)}, {chat_file.file_type})"
    ]
    if chat_file.parsed_content:
        parts.append(f"\nFirst {HEAD_LINES} lines:\n```\n{_head(chat_file.parsed_content)}\n```")
    return "".join(parts)


def _too_large_to_show(chat_file: ChatFile) -> str:
    """An image past the inline ceiling, with no workspace to put it in instead.

    Said rather than skipped: the person attached a picture and asked about it, so
    silence reads as the model ignoring them. Naming the limit is what tells them
    the fix is a smaller image rather than a better question.
    """
    return (
        f"\n---\nAttached image: {chat_file.filename} ({_size(chat_file)}) - too large "
        "to show, and this agent has no workspace to read it from. Attach a smaller "
        "version, or give the agent the Files & shell capability."
    )


def _unstored(chat_file: ChatFile) -> str:
    """Named and sampled, with no path offered because there is nothing at one.

    Never `_pasted`. This is only reached when the workspace refused the write,
    which for a full workspace means the file was too large to store - and a file
    too large for a four-megabyte document is too large to put in a prompt. The
    head is the usable part; the whole thing is the paste this module exists to
    replace.

    And no path, because the write failed: naming one the agent cannot open would
    cost it a tool call to discover a file that is not there.
    """
    parts = [
        f"\n---\nAttached file: {chat_file.filename} "
        f"({_size(chat_file)}, {chat_file.file_type}) - too large for the workspace, "
        "so it was not stored and cannot be opened as a file"
    ]
    if chat_file.parsed_content:
        parts.append(f"\nFirst {HEAD_LINES} lines:\n```\n{_head(chat_file.parsed_content)}\n```")
    return "".join(parts)


def _unreadable(chat_file: ChatFile) -> str:
    """A file no parser could read, with no workspace to open it from.

    Said rather than skipped, the same principle as `_too_large_to_show`: the
    person attached a file and asked about it, so an empty prompt reads as the
    model denying the file the transcript says arrived. There is nothing to
    sample and no path to give, so the model is told what came and why it cannot
    be opened.
    """
    return (
        f"\n---\nAttached file: {chat_file.filename} "
        f"({_size(chat_file)}, {chat_file.file_type}) - its text could not be extracted, "
        "and this agent has no workspace to open it from."
    )


def _unprocessable(chat_file: ChatFile) -> str:
    """Named when routing the file raised, so the turn survives but the model is
    not left denying it.

    The error's own text stays in the `logger.warning` beside the raise; the
    model is told only that the file arrived and could not be processed, which is
    all it can honestly say about it.
    """
    return (
        f"\n---\nAttached file: {chat_file.filename} "
        f"({_size(chat_file)}, {chat_file.file_type}) - it arrived but could not be "
        "processed, so its contents are unavailable."
    )


class AttachmentRouter:
    """Turns attached files into a prompt, and into files an agent can open.

    One object for every surface. The WebSocket built this inline and no other
    surface had it at all, so an attachment meant something different depending
    on where the person was sitting - and the workspace would have made that
    three different things.
    """

    def __init__(self, backend: BackendProtocol | AsyncBackendProtocol | None = None) -> None:
        # Wrapped here rather than at each `await` below, and rather than being the
        # caller's problem. A container-backed workspace is a synchronous
        # `httpx.Client`, so writing an upload into one from this coroutine blocked
        # the whole worker for the length of the transfer - a 50 MB CSV stalling
        # every other request in the process, which is the exact case a workspace
        # exists to make possible. `ensure_async` is the library's own answer and is
        # idempotent, so an already-async backend passes through untouched.
        self._backend = None if backend is None else ensure_async(backend)

    async def build_prompt(self, user_message: str, files: list[ChatFile]) -> str | list[Any]:
        """The user's message, with everything they attached folded in."""
        if not files:
            return user_message

        text_parts: list[str] = []
        inline: list[BinaryContent] = []
        for chat_file in files:
            plan = await self.route(chat_file)
            if plan.reference:
                text_parts.append(plan.reference)
            if plan.inline is not None:
                inline.append(plan.inline)

        full_text = user_message + "".join(text_parts)
        if inline:
            return [full_text, *inline]
        return full_text

    async def route(self, chat_file: ChatFile) -> AttachmentPlan:
        """Where one file goes, and what the model is told about it.

        A file that cannot be loaded is skipped rather than failing the turn:
        the user asked a question and attached something, and answering without
        the attachment beats not answering.
        """
        try:
            return await self._route(chat_file)
        except Exception:
            logger.warning(
                "attachment_routing_failed", extra={"file_id": str(chat_file.id)}, exc_info=True
            )
            return AttachmentPlan(reference=_unprocessable(chat_file), inline=None)

    async def _route(self, chat_file: ChatFile) -> AttachmentPlan:
        backend = self._backend
        if backend is None:
            return await self._without_workspace(chat_file)
        return await self._into_workspace(backend, chat_file)

    async def _without_workspace(self, chat_file: ChatFile) -> AttachmentPlan:
        """What an agent with nowhere to put files gets.

        The image ceiling applies here too. It used not to: this path inlined an
        image of any size while `_inline_image` beside it honoured
        `SANDBOX_INLINE_IMAGE_MAX_BYTES`, so the same 40 MB screenshot was refused
        by an agent *with* a workspace and loaded whole by one without - the wrong
        way round, since the one with a workspace has a path to offer instead and
        this one has nothing to fall back to.

        Past the ceiling the model is told the picture is there and too large,
        rather than being sent it or being told nothing. There is no path to give,
        so a person asking "what is in this screenshot" gets an answer about why it
        cannot be looked at instead of silence.
        """
        if chat_file.file_type == "image":
            inline = await self._inline_image(chat_file, None)
            if inline is None:
                return AttachmentPlan(reference=_too_large_to_show(chat_file), inline=None)
            return AttachmentPlan(reference=None, inline=inline)
        if chat_file.parsed_content:
            return AttachmentPlan(reference=_pasted(chat_file), inline=None)
        return AttachmentPlan(reference=_unreadable(chat_file), inline=None)

    async def _into_workspace(
        self, backend: AsyncBackendProtocol, chat_file: ChatFile
    ) -> AttachmentPlan:
        path = workspace_path(chat_file)
        data: bytes | None = None

        if not await backend.exists(path):
            data = await get_file_storage().load(chat_file.storage_path)
            result = await backend.write(path, data)
            if result.error is not None:
                # A full workspace, most likely - and that is exactly why this
                # must not fall back to pasting the file. The write is refused
                # when the document has no room for it, so this branch only ever
                # runs for a file too large to store; with a 50 MB upload limit
                # against a 4 MB document, pasting it would have put up to fifty
                # megabytes of text into one message. A file small enough to paste
                # safely would have fitted in the workspace.
                #
                # An image is the exception, and the reason is the same one that
                # makes images go both ways: the model can still *see* it, and
                # `_inline_image` has its own, much smaller ceiling.
                logger.info("attachment_not_written", extra={"path": path, "reason": result.error})
                if chat_file.file_type == "image":
                    return await self._without_workspace(chat_file)
                return AttachmentPlan(reference=_unstored(chat_file), inline=None)
            await self._write_extracted_text(backend, chat_file, path)

        if chat_file.file_type != "image":
            return AttachmentPlan(reference=_referenced(chat_file, path), inline=None)
        return AttachmentPlan(
            reference=_referenced(chat_file, path),
            inline=await self._inline_image(chat_file, data),
        )

    async def _write_extracted_text(
        self, backend: AsyncBackendProtocol, chat_file: ChatFile, path: str
    ) -> None:
        """Put the parse beside the original, for a format a shell cannot read.

        A PDF in a workspace is bytes an agent has no tool for; the text this
        platform already extracted is the useful half. Both are kept, because
        the original is what a person asked to be given and what an image
        conversion or a page count needs.

        A spreadsheet is the same case and it is worth saying why, because the
        obvious assumption is that an agent given the file can open it: it cannot.
        `run_python` has no filesystem at all - it is for arithmetic - and the
        workspace shell has no spreadsheet library, so `.xlsx` in a workspace is a
        zip of XML that `read_file` returns as mojibake. The `.txt` beside it is
        the only readable half.
        """
        if chat_file.file_type in {"pdf", "docx", "spreadsheet"} and chat_file.parsed_content:
            await backend.write(f"{path}.txt", chat_file.parsed_content)

    async def _inline_image(self, chat_file: ChatFile, data: bytes | None) -> BinaryContent | None:
        """The picture itself, when it is small enough to be worth sending twice.

        Past the ceiling the model gets the path and can `read_file` it
        deliberately - which for a large image is usually after resizing it,
        the thing it needed the file on disk for anyway.
        """
        if chat_file.size > settings.SANDBOX_INLINE_IMAGE_MAX_BYTES:
            return None
        if data is None:
            data = await get_file_storage().load(chat_file.storage_path)
        return BinaryContent(data=data, media_type=chat_file.mime_type)


async def load_attached_files(db: Any, file_ids: list[str], *, user_id: UUID) -> list[ChatFile]:
    """The rows behind the ids a client sent with its message, scoped to the sender (#706)."""
    from app.api.deps import get_conversation_service

    return await get_conversation_service(db).list_attached_files(file_ids, user_id=user_id)
