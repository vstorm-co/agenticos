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

from pydantic_ai.messages import BinaryContent

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


class AttachmentRouter:
    """Turns attached files into a prompt, and into files an agent can open.

    One object for every surface. The WebSocket built this inline and no other
    surface had it at all, so an attachment meant something different depending
    on where the person was sitting - and the workspace would have made that
    three different things.
    """

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend

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
            return AttachmentPlan(reference=None, inline=None)

    async def _route(self, chat_file: ChatFile) -> AttachmentPlan:
        backend = self._backend
        if backend is None:
            return await self._without_workspace(chat_file)
        return await self._into_workspace(backend, chat_file)

    async def _without_workspace(self, chat_file: ChatFile) -> AttachmentPlan:
        """The old behaviour, kept exactly, for an agent with nowhere to put files."""
        if chat_file.file_type == "image":
            data = await get_file_storage().load(chat_file.storage_path)
            return AttachmentPlan(
                reference=None,
                inline=BinaryContent(data=data, media_type=chat_file.mime_type),
            )
        if chat_file.parsed_content:
            return AttachmentPlan(reference=_pasted(chat_file), inline=None)
        return AttachmentPlan(reference=None, inline=None)

    async def _into_workspace(self, backend: Any, chat_file: ChatFile) -> AttachmentPlan:
        path = workspace_path(chat_file)
        data: bytes | None = None

        if not backend.exists(path):
            data = await get_file_storage().load(chat_file.storage_path)
            result = backend.write(path, data)
            if result.error is not None:
                # A full workspace, most likely. The file is still worth
                # mentioning - and for a parsed one the text is still usable -
                # so this degrades to the inline path rather than vanishing.
                logger.info("attachment_not_written", extra={"path": path, "reason": result.error})
                return await self._without_workspace(chat_file)
            self._write_extracted_text(backend, chat_file, path)

        if chat_file.file_type != "image":
            return AttachmentPlan(reference=_referenced(chat_file, path), inline=None)
        return AttachmentPlan(
            reference=_referenced(chat_file, path),
            inline=await self._inline_image(chat_file, data),
        )

    def _write_extracted_text(self, backend: Any, chat_file: ChatFile, path: str) -> None:
        """Put the parse beside the original, for a format a shell cannot read.

        A PDF in a workspace is bytes an agent has no tool for; the text this
        platform already extracted is the useful half. Both are kept, because
        the original is what a person asked to be given and what an image
        conversion or a page count needs.
        """
        if chat_file.file_type in {"pdf", "docx"} and chat_file.parsed_content:
            backend.write(f"{path}.txt", chat_file.parsed_content)

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


async def load_attached_files(db: Any, file_ids: list[str]) -> list[ChatFile]:
    """The rows behind the ids a client sent with its message."""
    from app.api.deps import get_conversation_service

    return await get_conversation_service(db).list_attached_files(file_ids)
