"""Keep a background result from racing a foreground conversation turn.

Only a small lease row is held across model calls, never a database transaction
or connection. Foreground turns still share admission, as project chats do now.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

import anyio
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AlreadyExistsError
from app.db.session import get_db_context
from app.repositories import conversation_task as task_repo

logger = logging.getLogger(__name__)


class _LostClaim(Exception):
    """The writer can no longer prove that its admission is current."""


WAIT_SECONDS = 60.0
RENEW_SECONDS = 15.0
RELEASE_SECONDS = 5.0


async def _renew(claim_id: UUID) -> None:
    while True:
        await anyio.sleep(RENEW_SECONDS)
        # A failure to prove ownership ends this turn; continuing could race the
        # next owner. The task group propagates the error and cancels its body.
        try:
            with anyio.fail_after(5):
                async with get_db_context() as db:
                    owned = await task_repo.renew_turn(db, claim_id)
        except (TimeoutError, SQLAlchemyError) as exc:
            raise _LostClaim from exc
        if not owned:
            raise _LostClaim


@asynccontextmanager
async def claim(conversation_id: UUID, *, background: bool) -> AsyncGenerator[bool]:
    """Yield admission; a background return defers instead of waiting for a worker slot."""
    claim_id: UUID | None = None
    with anyio.move_on_after(WAIT_SECONDS):
        while True:
            async with get_db_context() as db:
                claim_id = await task_repo.claim_turn(db, conversation_id, background=background)
            if claim_id is not None or background:
                break
            await anyio.sleep(0.25)
    if claim_id is None:
        if background:
            yield False
            return
        raise AlreadyExistsError(
            message="This conversation is receiving a task result. Try again shortly."
        )
    try:
        lost = False
        try:
            async with asyncio.TaskGroup() as group:
                keeper = group.create_task(_renew(claim_id))
                try:
                    yield True
                finally:
                    keeper.cancel()
        except* _LostClaim:
            lost = True
        if lost:
            raise AlreadyExistsError(
                message="This turn lost its conversation admission and was stopped. Check its saved answer before trying again."
            )
    finally:
        try:
            with anyio.move_on_after(RELEASE_SECONDS, shield=True) as closing:
                async with get_db_context() as db:
                    await task_repo.release_turn(db, claim_id)
            if closing.cancelled_caught:
                logger.warning("conversation_turn_release_timed_out")
        except SQLAlchemyError:
            # Only the bounded lease remains. It expires before another writer
            # is admitted; cleanup must not replace a turn's original failure.
            logger.warning("conversation_turn_release_failed")
