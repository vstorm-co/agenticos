"""Chat file repository."""

from collections.abc import Iterable
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agent_run import AgentRun, ApprovalDecidedVia, RunStatus, ToolApproval
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Message

_INTERRUPTED = [
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
    RunStatus.BUDGET_EXCEEDED.value,
    RunStatus.LOOP_STOPPED.value,
]
"""The endings of a turn that may have stopped before its files reached the
workspace - every one but completing, parking, still running and a guardrail's
block. A blocked turn was refused for what it carried, and its attachment's
opening lines are part of what the input edge screened: putting the file back
would hand a later turn what the policy turned away."""


class InterruptedFile(NamedTuple):
    """What `left_by_interrupted_turns` reads of a file - enough to find it on disk."""

    id: UUID
    filename: str
    file_type: str
    has_text: bool
    """Whether it has parsed text, which decides whether a text sibling is due."""


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


async def get_in_conversation(
    db: AsyncSession, file_id: UUID, *, conversation_id: UUID
) -> ChatFile | None:
    """One attachment, scoped to the thread whose turn it hangs on.

    The scope a run review needs and `user_id` cannot give: reading a run is the
    organization's right rather than its starter's, so a colleague holding
    `runs:view` reads a transcript whose attachments belong to somebody else. What
    replaces ownership is the turn - the file is admitted only where its
    `message_id` names a message of this conversation, which is the same reach the
    transcript route already grants.

    An unlinked file (`message_id` null) is nobody's transcript and resolves to
    nothing here: it is an upload in progress, and the only caller who should see
    one is the person holding it.
    """
    result = await db.execute(
        select(ChatFile)
        .join(Message, Message.id == ChatFile.message_id)
        .where(ChatFile.id == file_id, Message.conversation_id == conversation_id)
    )
    return result.scalar_one_or_none()


async def latest_named_in_conversation(
    db: AsyncSession, filename: str, *, conversation_id: UUID
) -> ChatFile | None:
    """The newest attachment of this name on one of the thread's turns.

    The scope is :func:`get_in_conversation`'s: a file is reached only where its
    message is in this conversation, so a name cannot reach another thread's
    upload. The newest, because a person who sends `logo.png` twice means the one
    they just sent.
    """
    result = await db.execute(
        select(ChatFile)
        .join(Message, Message.id == ChatFile.message_id)
        .where(ChatFile.filename == filename, Message.conversation_id == conversation_id)
        .order_by(ChatFile.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def left_by_interrupted_turns(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    limit: int,
) -> list[InterruptedFile]:
    """Where to look for `user_id`'s files on this agent's turns that did not
    finish here, since its last turn that did - newest first (#2481).

    Every predicate is a boundary. The file hangs on a prompt message of this
    conversation, that message's run is this organization's and this agent's,
    and the file is the caller's own: so a person's attachment is never written
    into another agent's workspace - one shared by everyone who runs it - nor
    into another member's run on a shared thread.

    The run's status is what says the file may never have reached the workspace.
    A completed turn routed its files, and one the workspace refused was named
    to the model as unstored; a missing file there was removed, and is left
    removed. And only until this agent completes a turn for the same person
    that started after the interrupted one ended: that turn has had its chance
    to put a lost file back, so a file somebody deleted after it stays deleted.
    Another person's turn closes nothing - it never puts this person's files
    back - and neither does one that was already running when this one stopped.

    A few columns rather than rows: a row carries the file's parsed text, up to
    a million characters, and the caller needs the text only for a file its
    workspace turns out to be missing.
    """
    result = await db.execute(
        _left_by_interrupted_turns(
            select(
                ChatFile.id,
                ChatFile.filename,
                ChatFile.file_type,
                func.coalesce(func.length(ChatFile.parsed_content), 0) > 0,
            ),
            conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            agent_id=agent_id,
        )
        .order_by(ChatFile.created_at.desc())
        .limit(limit)
    )
    return [InterruptedFile(*row) for row in result.all()]


async def get_many_left_by_interrupted_turns(
    db: AsyncSession,
    file_ids: Iterable[UUID],
    *,
    conversation_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    agent_id: UUID,
) -> list[ChatFile]:
    """These files, as whole rows, under exactly `left_by_interrupted_turns`'s conditions.

    Asked again rather than read by id: the ids were found in another session,
    and the boundaries are what makes writing a file into this run's workspace
    allowed at all.
    """
    ids = list(file_ids)
    if not ids:
        return []
    result = await db.execute(
        _left_by_interrupted_turns(
            select(ChatFile),
            conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            agent_id=agent_id,
        )
        .where(ChatFile.id.in_(ids))
        .order_by(ChatFile.created_at.desc())
    )
    return list(result.scalars().all())


def _left_by_interrupted_turns[*Ts](
    statement: Select[*Ts],
    *,
    conversation_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    agent_id: UUID,
) -> Select[*Ts]:
    """The conditions both reads share - see `left_by_interrupted_turns`.

    The completed turn that closes the window is asked about per candidate,
    correlated on the candidate's own run, so a thread whose turns all finished
    pays nothing for it. Only a turn that looked for these files closes it - one
    the person started themselves, in a session, and not continued by somebody
    else: a key's run, a publisher standing in for a visitor and a run resumed
    by another approver all skip the look (`AgentRunnerService._assemble`), so
    their finishing proves nothing.
    """
    closing = aliased(AgentRun)
    released_by_another = (
        select(ToolApproval.id)
        .where(
            ToolApproval.run_id == closing.id,
            ToolApproval.decided_via == ApprovalDecidedVia.CLICK.value,
            ToolApproval.decided_by_user_id.is_distinct_from(closing.user_id),
        )
        .exists()
    )
    closed = (
        select(closing.id)
        .where(
            closing.conversation_id == conversation_id,
            closing.agent_id == agent_id,
            closing.user_id == user_id,
            closing.status == RunStatus.COMPLETED.value,
            closing.created_at > func.coalesce(AgentRun.ended_at, AgentRun.created_at),
            # A key's run records the key's scopes as an array; a session's
            # records none, as SQL or as JSON null.
            func.jsonb_typeof(closing.key_scopes).is_distinct_from("array"),
            closing.initiated_by_publisher_fallback.is_(False),
            ~released_by_another,
        )
        .exists()
    )
    return (
        statement.join(Message, Message.id == ChatFile.message_id)
        .join(AgentRun, AgentRun.id == Message.run_id)
        .where(
            Message.conversation_id == conversation_id,
            AgentRun.conversation_id == conversation_id,
            AgentRun.organization_id == organization_id,
            AgentRun.agent_id == agent_id,
            AgentRun.status.in_(_INTERRUPTED),
            ChatFile.user_id == user_id,
            ~closed,
        )
    )


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


async def unlinked_ids(db: AsyncSession, file_ids: Iterable[UUID]) -> set[UUID]:
    """Of these files, the ids whose row is not yet attached to a message.

    A turn's attachments are linked when the runner records its transcript - a
    failed turn included, which persists and commits before it re-raises - so a
    file already carrying a `message_id` belongs to a stored turn and must not be
    swept up as an orphan (#1503). Read as a column select rather than through the
    mapped rows: the link is a bulk UPDATE the session never saw and
    `expire_on_commit` is off, so a loaded instance still reads `message_id` as
    None.
    """
    ids = list(file_ids)
    if not ids:
        return set()
    result = await db.execute(
        select(ChatFile.id).where(ChatFile.id.in_(ids), ChatFile.message_id.is_(None))
    )
    return set(result.scalars().all())


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
