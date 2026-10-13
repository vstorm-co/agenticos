"""A /link confirm racing a concurrent inbound message links one identity.

`ChannelLinkService.confirm` used to get-then-create the identity - the same
unlocked check-then-act #17 closed in the router. A user who sends a message (the
router's own INSERT) at the moment they click the confirm could make confirm's
INSERT collide on `uq_channel_identity_platform_user` and 500 the confirm
(#1113). Routing confirm through `get_or_create` (SELECT-first, ON CONFLICT DO
NOTHING) closes it, and only the database can show it, because what makes it work
is the unique index across two transactions.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.user import User
from app.repositories import channel_identity_repo, channel_link_request_repo
from app.services.channel_link import ChannelLinkService

pytestmark = pytest.mark.anyio


async def test_a_confirm_racing_an_inbound_message_still_links_one_identity(
    engine: AsyncEngine,
) -> None:
    """One webhook's identity insert is held open (uncommitted, the unique-index
    lock on the new row) while a /link confirm resolves the same platform user.

    The confirm's `get_or_create` blocks on that lock and, once the inbound
    commits, resolves the row it lost to and links it - one identity, no error,
    the confirm's user_id landing on it. The get-then-create it replaces would
    instead have the confirm's own INSERT unblock into a
    `uq_channel_identity_platform_user` violation and 500 the confirm.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    platform = "slack"
    platform_user_id = uuid.uuid4().hex

    async with factory() as setup:
        user = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        setup.add(user)
        await channel_link_request_repo.create(
            setup,
            token="tok-race",
            platform=platform,
            platform_user_id=platform_user_id,
            platform_username=None,
            platform_display_name=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await setup.commit()
        user_id = user.id

    session_a = factory()
    confirm_task: asyncio.Task[object] | None = None
    try:
        # The inbound message's transaction resolves (creates) the identity and
        # holds it open: the unique-index lock on the new row, uncommitted.
        await channel_identity_repo.get_or_create(
            session_a, platform=platform, platform_user_id=platform_user_id, user_id=None
        )

        async def confirm() -> object:
            async with factory() as session_b:
                spent = await ChannelLinkService(session_b).confirm("tok-race", user_id)
                await session_b.commit()
                return spent

        confirm_task = asyncio.create_task(confirm())
        await asyncio.sleep(0.4)
        assert not confirm_task.done()  # blocked on A's uncommitted insert

        await session_a.commit()

        spent = await confirm_task
        confirm_task = None
        assert spent is not None  # the confirm succeeded rather than 500ing
    finally:
        if confirm_task is not None:
            confirm_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await confirm_task
        await session_a.close()

    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ChannelIdentity)
            .where(
                ChannelIdentity.platform == platform,
                ChannelIdentity.platform_user_id == platform_user_id,
            )
        )
        assert count == 1  # exactly one identity, not two

        identity = await channel_identity_repo.get_by_platform_user(
            session, platform=platform, platform_user_id=platform_user_id
        )
        assert identity is not None
        assert identity.user_id == user_id  # the confirm's link landed


async def test_two_confirms_of_one_token_leave_a_single_claimant(
    engine: AsyncEngine,
) -> None:
    """A /link token is a single-use bearer credential. Two authenticated users
    confirming it at once both read it as valid; consuming the request before
    relinking lets only one win, so the token cannot be replayed to overwrite the
    first claimant's link (#1132).
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    platform = "slack"
    platform_user_id = uuid.uuid4().hex

    async with factory() as setup:
        user_a = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        user_b = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        setup.add_all([user_a, user_b])
        await channel_link_request_repo.create(
            setup,
            token="tok-double",
            platform=platform,
            platform_user_id=platform_user_id,
            platform_username=None,
            platform_display_name=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await setup.commit()
        a_id, b_id = user_a.id, user_b.id

    async def confirm_as(user_id: uuid.UUID) -> object:
        async with factory() as session:
            spent = await ChannelLinkService(session).confirm("tok-double", user_id)
            await session.commit()
            return spent

    results = await asyncio.gather(confirm_as(a_id), confirm_as(b_id))

    # Exactly one confirm claimed the token; the other found it already spent.
    assert sorted(r is None for r in results) == [False, True]

    async with factory() as session:
        identities = (
            (
                await session.execute(
                    select(ChannelIdentity).where(
                        ChannelIdentity.platform == platform,
                        ChannelIdentity.platform_user_id == platform_user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(identities) == 1  # one identity, linked to whichever confirm won
        assert identities[0].user_id in {a_id, b_id}
