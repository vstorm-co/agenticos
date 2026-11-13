"""Short, shared admission for conversation workspace writers and task undo."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError
from app.db.locks import LockScope, try_hold_subject
from app.repositories import agent_run as run_repo
from app.repositories import coding_task_change as change_repo


async def admit(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    run_id: UUID | None = None,
    change_id: UUID | None = None,
) -> None:
    """Never wait for another admission, or keep this transaction over external work.

    A run's existing RUNNING row protects its lifetime after the opening commit.
    An undo's job reservation does the same until its outcome is established.
    """
    if not await try_hold_subject(db, LockScope.CONVERSATION_TURN, conversation_id):
        raise AlreadyExistsError(
            message="This conversation's workspace is busy. Try again shortly.", details={}
        )
    if await run_repo.has_running_in_conversation(
        db, organization_id=organization_id, conversation_id=conversation_id, excluding=run_id
    ) or await change_repo.has_pending_revert(
        db, organization_id=organization_id, conversation_id=conversation_id, excluding=change_id
    ):
        raise AlreadyExistsError(
            message="This conversation's workspace has an active writer or an unresolved revert.",
            details={},
        )
