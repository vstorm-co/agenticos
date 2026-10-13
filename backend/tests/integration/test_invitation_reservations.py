"""A capped link bounds accounts, not only joins - against a real database.

`used_count` counts acceptances, and acceptance needs a signed-in user. So on an
`invite_only` deployment a `max_uses=1` link admitted an unbounded number of
*registrations*: every one of them read a count nothing had yet moved. One link
posted in a channel, and closing sign-up was closed to nobody.

A use is reserved for the registering address before the account exists, and the
reservation is a single conditional `UPDATE` - which is the half only Postgres can
answer. A mock can prove the policy asks; only the database can prove that two
registrations racing on the last use do not both get it, because what makes it true
is the row lock and the `WHERE` being re-evaluated against the version it locked.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.organization import Invitation, InvitationStatus, Organization
from app.db.models.user import User
from app.repositories import invitation_repo

pytestmark = pytest.mark.anyio


async def _link(db, *, max_uses: int | None, used_count: int = 0) -> Invitation:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    invite = Invitation(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=None,
        max_uses=max_uses,
        used_count=used_count,
        invited_by_user_id=user.id,
        token=secrets.token_urlsafe(32),
        status=InvitationStatus.PENDING.value,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invite)
    await db.flush()
    await db.refresh(invite)
    return invite


async def test_the_column_defaults_to_an_empty_list_rather_than_null(db) -> None:
    """The arithmetic and the containment test both read it on every gated
    registration, so a null would mean a coalesce in two more places."""
    invite = await _link(db, max_uses=1)

    assert invite.reserved_emails == []


async def test_a_use_is_held_for_the_address_that_registered(db) -> None:
    invite = await _link(db, max_uses=2)

    assert await invitation_repo.reserve_use(db, invitation_id=invite.id, email="One@Acme.com")

    await db.refresh(invite)
    assert invite.reserved_emails == ["one@acme.com"]


async def test_a_second_address_cannot_take_the_last_use(db) -> None:
    """The defect, at its smallest: a one-use link admitting a second account."""
    invite = await _link(db, max_uses=1)
    assert await invitation_repo.reserve_use(db, invitation_id=invite.id, email="one@acme.com")

    assert not await invitation_repo.reserve_use(db, invitation_id=invite.id, email="two@acme.com")

    await db.refresh(invite)
    assert invite.reserved_emails == ["one@acme.com"]


async def test_the_same_address_reserving_twice_is_still_one_use(db) -> None:
    """Idempotent, so a registration retried after a network error is not refused by
    the reservation its own first attempt made."""
    invite = await _link(db, max_uses=1)

    assert await invitation_repo.reserve_use(db, invitation_id=invite.id, email="one@acme.com")
    assert await invitation_repo.reserve_use(db, invitation_id=invite.id, email="ONE@acme.com")

    await db.refresh(invite)
    assert invite.reserved_emails == ["one@acme.com"]


async def test_an_acceptance_already_counted_leaves_less_room(db) -> None:
    invite = await _link(db, max_uses=2, used_count=1)
    assert await invitation_repo.reserve_use(db, invitation_id=invite.id, email="one@acme.com")

    assert not await invitation_repo.reserve_use(db, invitation_id=invite.id, email="two@acme.com")


async def test_an_uncapped_link_holds_nothing_against_anybody(db) -> None:
    invite = await _link(db, max_uses=None)

    assert await invitation_repo.reserve_use(db, invitation_id=invite.id, email="one@acme.com")
    assert await invitation_repo.reserve_use(db, invitation_id=invite.id, email="two@acme.com")


async def test_accepting_moves_the_reservation_into_the_count(db) -> None:
    """What conserves the capacity: a person who registered through a one-use link
    can still join, and the link is spent exactly once."""
    invite = await _link(db, max_uses=1)
    await invitation_repo.reserve_use(db, invitation_id=invite.id, email="one@acme.com")
    # Reloaded, because a bulk UPDATE expires the instance and the two steps are two
    # requests in the product: registration holds the use, and the acceptance that
    # releases it happens once the person has a session.
    await db.refresh(invite)

    await invitation_repo.record_use(db, invite, email="One@Acme.com")

    await db.refresh(invite)
    assert (invite.used_count, invite.reserved_emails) == (1, [])
    assert invite.status == InvitationStatus.ACCEPTED.value


async def test_an_acceptance_by_somebody_who_never_registered_leaves_reservations_alone(
    db,
) -> None:
    """Two people, one use each: the acceptance must not release the other's hold."""
    invite = await _link(db, max_uses=2)
    await invitation_repo.reserve_use(db, invitation_id=invite.id, email="one@acme.com")
    await db.refresh(invite)

    await invitation_repo.record_use(db, invite, email="two@acme.com")

    await db.refresh(invite)
    assert (invite.used_count, invite.reserved_emails) == (1, ["one@acme.com"])


async def test_two_registrations_racing_on_the_last_use_do_not_both_get_it(db, engine) -> None:
    """The reason this is a conditional UPDATE and not a count read in Python.

    Two sessions, so two transactions: the second blocks on the row lock the first
    took, and Postgres re-evaluates the `WHERE` against the version it locked - so
    it sees the reservation the first one committed and is refused. Read-then-write
    would have both of them reading zero.
    """
    invite = await _link(db, max_uses=1)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def reserve(email: str) -> bool:
        async with factory() as session:
            held = await invitation_repo.reserve_use(session, invitation_id=invite.id, email=email)
            await session.commit()
            return held

    first, second = await asyncio.gather(reserve("one@acme.com"), reserve("two@acme.com"))

    assert [first, second].count(True) == 1
    await db.refresh(invite)
    assert len(invite.reserved_emails) == 1


async def _acceptor(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def test_two_accepts_of_a_one_use_link_admit_exactly_one_member(db, engine) -> None:
    """The acceptance-side race, which `reserve_use` does not cover.

    `accept` reads `used_count`, checks it against `max_uses`, and increments -
    unlocked, two accepts of a one-use link both read zero and both create a
    member (#17). Locking the invitation row in `accept` serializes them.

    Deterministic on purpose: one acceptance is held open (uncommitted, lock on
    the invitation row) while the other runs. With the lock the second blocks on
    the `get_by_token` read and, once the first commits, re-reads an exhausted
    link and is refused; without it the second blocks later on the `record_use`
    write, having already passed the guard against a `used_count` of zero, and a
    second member is created. `gather` alone does not reproduce it - the pair
    serialises and the first commits before the second reads.
    """
    from app.core.exceptions import BadRequestError
    from app.repositories import member_repo
    from app.services.invitation import InvitationService

    invite = await _link(db, max_uses=1)
    one = await _acceptor(db)
    two = await _acceptor(db)
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_a = factory()
    b_task: asyncio.Task[None] | None = None
    try:
        await InvitationService(session_a).accept(invite.token, accepting_user_id=one.id)

        async def accept_b() -> None:
            async with factory() as session_b:
                await InvitationService(session_b).accept(invite.token, accepting_user_id=two.id)
                await session_b.commit()

        b_task = asyncio.create_task(accept_b())
        await asyncio.sleep(0.4)
        assert not b_task.done()  # blocked on A's lock

        await session_a.commit()

        with pytest.raises(BadRequestError):
            await b_task
        b_task = None
    finally:
        if b_task is not None:
            b_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await b_task
        await session_a.close()

    members = await member_repo.count_for_org(db, invite.organization_id)
    assert members == 1
