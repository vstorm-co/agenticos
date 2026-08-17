"""Chat file repository."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chat_file import ChatFile


async def get_by_id(db: AsyncSession, file_id: UUID) -> ChatFile | None:
    """Get a chat file by ID."""
    return await db.get(ChatFile, file_id)


async def get_many(db: AsyncSession, file_ids: Iterable[UUID], *, user_id: UUID) -> list[ChatFile]:
    """Batch-load `user_id`'s chat files by IDs.

    The ids come off client payloads, and `chat_files` carries no organization,
    so `user_id` is the only scope a row has: another user's id resolves to
    nothing here rather than to their row (#706).
    """
    ids = list(file_ids)
    if not ids:
        return []
    result = await db.execute(
        select(ChatFile).where(ChatFile.id.in_(ids), ChatFile.user_id == user_id)
    )
    return list(result.scalars().all())


async def link_to_message(
    db: AsyncSession, *, message_id: UUID, file_ids: Iterable[UUID], user_id: UUID
) -> int:
    """Link `user_id`'s unlinked chat files to a message, answering how many moved.

    The WHERE carries both halves of the rule rather than trusting the caller:
    without them this was a blind bulk update, so a turn naming another user's
    file id put their filename on its own message and silently pulled the file
    off the message it already hung on (#706). An id the predicates exclude is
    skipped here; a caller that must refuse it reads the rows first
    (`ConversationService.link_files_to_message`) - and compares the count,
    because a concurrent turn can take a row between that read and this UPDATE.
    """
    ids = list(file_ids)
    if not ids:
        return 0
    result = await db.execute(
        sql_update(ChatFile)
        .where(
            ChatFile.id.in_(ids),
            ChatFile.user_id == user_id,
            ChatFile.message_id.is_(None),
        )
        .values(message_id=message_id)
    )
    await db.flush()
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement actually returns `CursorResult`, which does (see resource_grant).
    return result.rowcount  # ty: ignore[unresolved-attribute]


async def delete(db: AsyncSession, *, db_file: ChatFile) -> None:
    """Delete a chat file row."""
    await db.delete(db_file)
    await db.flush()


async def create(
    db: AsyncSession,
    *,
    user_id: UUID,
    filename: str,
    mime_type: str,
    size: int,
    storage_path: str,
    file_type: str,
    parsed_content: str | None = None,
) -> ChatFile:
    """Create a new chat file record."""
    chat_file = ChatFile(
        user_id=user_id,
        filename=filename,
        mime_type=mime_type,
        size=size,
        storage_path=storage_path,
        file_type=file_type,
        parsed_content=parsed_content,
    )
    db.add(chat_file)
    await db.flush()
    return chat_file
