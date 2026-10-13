"""Two app admins deleting each other must not leave a deployment with none.

`admin_delete` refuses an app admin deleting *themselves*, and that is what keeps
the last administrator from being the one removed - because `is_app_admin` cannot
be cleared over the API, so the set only ever shrinks by deletion. The guard is a
comparison inside one request, and two requests both passed it: A deleting B and
B deleting A are each not-self, they locked different target rows, they never
contended, and both committed. Nobody was left who could sign in to administer the
deployment, and the only recovery is a direct database write (#1208).

Only a database can show either half of the fix - that the second request *waits*,
and that it is refused once it can see the first one's commit - because what makes
it work is `SELECT ... FOR UPDATE` over the app-admin set across two transactions.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import AuthorizationError
from app.db.models.user import User
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def _admin(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
        is_app_admin=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _app_admins(factory) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count(User.id)).where(User.is_app_admin.is_(True)))


class TestTheSetIsWhatIsLocked:
    async def test_the_second_of_two_mutual_deletes_is_refused(self, engine: AsyncEngine) -> None:
        """Deterministic rather than raced: A's delete is held open, holding the
        lock on the admin set, while B's mirror-image delete runs. B blocks, and
        once A commits it re-reads a set of one and is refused."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            first = await _admin(setup)
            second = await _admin(setup)
            await setup.commit()

        session_a = factory()
        b_task: asyncio.Task[None] | None = None
        try:
            await UserService(session_a).admin_delete(second.id, acting_admin_id=first.id)

            async def delete_the_other() -> None:
                async with factory() as session_b:
                    with pytest.raises(AuthorizationError):
                        await UserService(session_b).admin_delete(
                            first.id, acting_admin_id=second.id
                        )
                    await session_b.commit()

            b_task = asyncio.create_task(delete_the_other())
            await asyncio.sleep(0.4)
            assert not b_task.done()  # blocked on A's lock over the admin set

            await session_a.commit()

            await b_task
            b_task = None
        finally:
            if b_task is not None:
                b_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await b_task
            await session_a.close()

        assert await _app_admins(factory) == 1

    async def test_one_of_three_admins_may_still_go(self, engine: AsyncEngine) -> None:
        """The refusal is about emptying the set, not about touching it."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            actor = await _admin(setup)
            doomed = await _admin(setup)
            await _admin(setup)
            await setup.commit()

        async with factory() as session:
            await UserService(session).admin_delete(doomed.id, acting_admin_id=actor.id)
            await session.commit()

        assert await _app_admins(factory) == 2
