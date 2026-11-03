"""Two people confirming one WhatsApp link URL leave exactly one code (#2076).

`claim_for_code` is a single conditional UPDATE: the row lock makes the second
confirmer re-check `confirmed_user_id IS NULL` after the first commits and match
nothing. Only the database can show it - the unit tests mock the repository.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_link_request import ChannelLinkRequest
from app.db.models.user import User
from app.repositories import channel_link_request_repo
from app.services.channel_link import ChannelLinkService
from app.services.channels.base import IncomingMessage

pytestmark = pytest.mark.anyio


async def test_two_confirmers_one_code(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    platform_user_id = f"{uuid.uuid4()}:{uuid.uuid4().hex}"
    token = uuid.uuid4().hex

    async with factory() as setup:
        users = [
            User(
                id=uuid.uuid4(),
                email=f"{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                is_active=True,
            )
            for _ in range(2)
        ]
        setup.add_all(users)
        await channel_link_request_repo.create(
            setup,
            token=token,
            platform="whatsapp",
            platform_user_id=platform_user_id,
            platform_username="•••• 1234",
            platform_display_name=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await setup.commit()
        ids = [user.id for user in users]

    async def confirm_as(user_id: uuid.UUID) -> object:
        async with factory() as session:
            issued = await ChannelLinkService(session).confirm(token, user_id)
            await session.commit()
            return issued

    results = await asyncio.gather(confirm_as(ids[0]), confirm_as(ids[1]))

    assert sorted(r is None for r in results) == [False, True]

    async with factory() as session:
        request = (
            await session.execute(
                select(ChannelLinkRequest).where(ChannelLinkRequest.token == token)
            )
        ).scalar_one()
        assert request.confirmed_user_id in ids
        assert request.confirm_code is not None and len(request.confirm_code) == 6
        # Nothing was linked by the browser step.
        assert (
            await session.execute(
                select(ChannelIdentity).where(ChannelIdentity.platform_user_id == platform_user_id)
            )
        ).scalar_one_or_none() is None

    # The chat then sends the code: the identity gains exactly the winner.
    async with factory() as session:
        outcome = await ChannelLinkService(session).complete_with_code(
            IncomingMessage(
                platform="whatsapp",
                bot_id=str(uuid.uuid4()),
                platform_user_id=platform_user_id,
                platform_chat_id="x",
                chat_type="private",
                text=request.confirm_code,
                raw={},
            )
        )
        await session.commit()
    assert outcome == "linked"
    async with factory() as session:
        identity = (
            await session.execute(
                select(ChannelIdentity).where(ChannelIdentity.platform_user_id == platform_user_id)
            )
        ).scalar_one()
        assert identity.user_id == request.confirmed_user_id


async def test_one_user_losing_the_claim_to_their_other_tab_gets_the_same_code(
    engine: AsyncEngine,
) -> None:
    """Two tabs of one person. The first confirm is held uncommitted, so the second
    reads the request as unconfirmed, blocks on the row lock, loses the claim once the
    first commits, and reads the winner's code back instead of a 404."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid.uuid4().hex
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    async with factory() as setup:
        setup.add(user)
        await channel_link_request_repo.create(
            setup,
            token=token,
            platform="whatsapp",
            platform_user_id=f"{uuid.uuid4()}:{uuid.uuid4().hex}",
            platform_username=None,
            platform_display_name=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await setup.commit()

    session_a = factory()
    second: asyncio.Task[str | None] | None = None
    try:
        won = await ChannelLinkService(session_a).confirm(token, user.id)
        assert won is not None and won.confirm_code is not None  # held: uncommitted

        async def confirm_in_the_other_tab() -> str | None:
            async with factory() as session_b:
                issued = await ChannelLinkService(session_b).confirm(token, user.id)
                await session_b.commit()
                return None if issued is None else issued.confirm_code

        second = asyncio.create_task(confirm_in_the_other_tab())
        await asyncio.sleep(0.4)
        assert not second.done()  # blocked on A's row lock

        code = won.confirm_code
        await session_a.commit()
        assert await second == code
        second = None
    finally:
        if second is not None:
            second.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await second
        await session_a.close()


async def test_the_second_claim_waits_for_the_first_and_then_loses(engine: AsyncEngine) -> None:
    """The first claim is held uncommitted; the second blocks on the row lock and,
    once the first commits, re-checks `confirmed_user_id IS NULL` and matches
    nothing. Deterministic: it does not rely on two sessions happening to
    interleave."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid.uuid4().hex

    async with factory() as setup:
        users = [
            User(
                id=uuid.uuid4(),
                email=f"{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                is_active=True,
            )
            for _ in range(2)
        ]
        setup.add_all(users)
        request = await channel_link_request_repo.create(
            setup,
            token=token,
            platform="whatsapp",
            platform_user_id=f"{uuid.uuid4()}:{uuid.uuid4().hex}",
            platform_username=None,
            platform_display_name=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await setup.commit()
        request_id, first, second = request.id, users[0].id, users[1].id

    expires = datetime.now(UTC) + timedelta(minutes=5)
    session_a = factory()
    claim_b: asyncio.Task[bool] | None = None
    try:
        won = await channel_link_request_repo.claim_for_code(
            session_a, request_id=request_id, user_id=first, code="111111", expires_at=expires
        )
        assert won is True  # held: uncommitted, the row lock

        async def claim_as_second() -> bool:
            async with factory() as session_b:
                claimed = await channel_link_request_repo.claim_for_code(
                    session_b,
                    request_id=request_id,
                    user_id=second,
                    code="222222",
                    expires_at=expires,
                )
                await session_b.commit()
                return claimed

        claim_b = asyncio.create_task(claim_as_second())
        await asyncio.sleep(0.4)
        assert not claim_b.done()  # blocked on A's row lock

        await session_a.commit()
        assert await claim_b is False
        claim_b = None
    finally:
        if claim_b is not None:
            claim_b.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await claim_b
        await session_a.close()

    async with factory() as session:
        row = (
            await session.execute(
                select(ChannelLinkRequest).where(ChannelLinkRequest.token == token)
            )
        ).scalar_one()
        assert (row.confirmed_user_id, row.confirm_code) == (first, "111111")
