"""One person, two chats, two webhooks at once: still one identity row.

A Slack user messaging two channels at the same moment produces two webhooks
whose sessions both resolve the same identity. Unlocked get-then-create had them
both miss the `SELECT` and both `INSERT`, and the second violated
`uq_channel_identity_platform_user` - so the whole event failed and that user got
no reply (#17). The in-process lock did not help: it is keyed on the chat, so the
two webhooks held different locks. Only the database can show the fix, because
what makes it work is `ON CONFLICT` against the unique index across two
transactions.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.channel_identity import ChannelIdentity
from app.repositories import channel_identity_repo

pytestmark = pytest.mark.anyio


async def test_a_held_insert_does_not_make_the_second_resolve_fail(
    engine: AsyncEngine,
) -> None:
    """Deterministic on purpose: one webhook's insert is held open (uncommitted,
    the unique-index lock on the new row) while the other resolves the same user.

    With `ON CONFLICT DO UPDATE` the second blocks on that lock and, once the
    first commits, resolves the existing row - one identity, no error. The naive
    get-then-create it replaces would instead have the second's own `INSERT`
    unblock into a `uq_channel_identity_platform_user` violation and fail the
    event. Racing two resolves through `gather` alone does not reproduce this: the
    pair serialises and the first commits before the second inserts.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    platform = "slack"
    platform_user_id = uuid.uuid4().hex

    session_a = factory()
    b_task: asyncio.Task[uuid.UUID] | None = None
    try:
        first = await channel_identity_repo.get_or_create(
            session_a, platform=platform, platform_user_id=platform_user_id
        )

        async def resolve_b() -> uuid.UUID:
            async with factory() as session_b:
                identity = await channel_identity_repo.get_or_create(
                    session_b, platform=platform, platform_user_id=platform_user_id
                )
                await session_b.commit()
                return identity.id

        b_task = asyncio.create_task(resolve_b())
        await asyncio.sleep(0.4)
        assert not b_task.done()  # blocked on A's uncommitted insert

        await session_a.commit()

        second = await b_task
        b_task = None
        assert second == first.id  # the same identity, no error
    finally:
        if b_task is not None:
            b_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await b_task
        await session_a.close()

    async with factory() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(ChannelIdentity)
            .where(
                ChannelIdentity.platform == platform,
                ChannelIdentity.platform_user_id == platform_user_id,
            )
        )
        assert rows == 1
